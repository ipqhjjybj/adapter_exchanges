import aiohttp
import asyncio
import hashlib
import logging
import random
import re
import time
from enum import IntEnum
from typing import Callable, Dict, Optional, Tuple, Sequence, Union, cast
from typing import List, Optional

from eth_account.messages import encode_structured_data
from eth_account.signers.local import LocalAccount
from web3.auto import Web3, w3
from web3.middleware import construct_sign_and_send_raw_middleware

from starknet_py.common import int_from_bytes
from starknet_py.constants import RPC_CONTRACT_ERROR
from starknet_py.hash.address import compute_address
from starknet_py.hash.selector import get_selector_from_name
from starknet_py.net.client import Client
from starknet_py.net.client_errors import ClientError
from starknet_py.net.client_models import Call, Hash, TransactionExecutionStatus, TransactionFinalityStatus
from starknet_py.net.full_node_client import FullNodeClient
from starknet_py.net.models import Address
from starknet_py.net.signer.stark_curve_signer import KeyPair
from starknet_py.proxy.contract_abi_resolver import ProxyConfig
from starknet_py.proxy.proxy_check import ArgentProxyCheck, OpenZeppelinProxyCheck, ProxyCheck
from starknet_py.transaction_errors import (
    TransactionRevertedError,
    TransactionNotReceivedError,
)
from starkware.crypto.signature.signature import generate_k_rfc6979
from starknet_py.utils.typed_data import TypedData
from starkware.crypto.signature.signature import EC_ORDER
from starknet_py.net.account.account import Account as StarknetAccount
from starknet_py.net.client import Client
from starknet_py.net.models import AddressRepresentation, StarknetChainId
from starknet_py.net.signer import BaseSigner
from starknet_py.net.signer.stark_curve_signer import KeyPair
from starknet_py.utils.typed_data import TypedData as TypedDataDataclass
from starknet_crypto_py import (
    get_public_key as rs_get_public_key,
    pedersen_hash as rs_pedersen_hash,
    sign as rs_sign,
    verify as rs_verify,
)
from starknet_py.utils.typed_data import (
    TypedData as StarknetTypedDataDataclass,
    get_hex,
    is_pointer,
    strip_pointer,
)

def hex_to_int(val: str):
    return int(val, 16)


def get_chain_id(chain_id: str):
    class CustomStarknetChainId(IntEnum):
        PRIVATE_TESTNET = int_from_bytes(chain_id.encode("UTF-8"))
    return CustomStarknetChainId.PRIVATE_TESTNET

def private_to_stark_key(priv_key: int) -> int:
    """
    Deduces the public key given a private key.
    """
    return rs_get_public_key(priv_key)


def pedersen_hash(left: int, right: int) -> int:
    """
    One of two hash functions (along with _starknet_keccak) used throughout Starknet.
    """
    # return cpp_hash(left, right)
    return rs_pedersen_hash(left, right)


def compute_hash_on_elements(data: Sequence) -> int:
    """
    Computes a hash chain over the data, in the following order:
        h(h(h(h(0, data[0]), data[1]), ...), data[n-1]), n).

    The hash is initialized with 0 and ends with the data length appended.
    The length is appended in order to avoid collisions of the following kind:
    H([x,y,z]) = h(h(x,y),z) = H([w, z]) where w = h(x,y).
    """
    return functools.reduce(pedersen_hash, [*data, len(data)], 0)


def message_signature(
    msg_hash: int, priv_key: int, seed: Optional[int] = None
) -> tuple[int, int]:
    """
    Signs the message with private key.
    """
    # k should be a strong cryptographical random
    # See: https://tools.ietf.org/html/rfc6979
    k = generate_k_rfc6979(msg_hash, priv_key, seed)
    return rs_sign(private_key=priv_key, msg_hash=msg_hash, k=k)


def verify_message_signature(
    msg_hash: int, signature: List[int], public_key: int
) -> bool:
    """
    Verifies ECDSA signature of a given message hash with a given public key.
    Returns true if public_key signs the message.
    """
    r, s = signature
    return rs_verify(msg_hash=msg_hash, r=r, s=s, public_key=public_key)


class TypedData(StarknetTypedDataDataclass):
    def _encode_data(self, type_name: str, data: dict) -> List[int]:
        values = []
        for param in self.types[type_name]:
            encoded_value = self._encode_value(param.type, data[param.name])
            values.append(encoded_value)

        return values

    def _encode_value(self, type_name: str, value: Union[int, str, dict, list]) -> int:
        if is_pointer(type_name) and isinstance(value, list):
            type_name = strip_pointer(type_name)

            if self._is_struct(type_name):
                return compute_hash_on_elements(
                    [self.struct_hash(type_name, data) for data in value]
                )
            return compute_hash_on_elements([int(get_hex(val), 16) for val in value])

        if self._is_struct(type_name) and isinstance(value, dict):
            return self.struct_hash(type_name, value)

        value = cast(Union[int, str], value)
        return int(get_hex(value), 16)

    def struct_hash(self, type_name: str, data: dict) -> int:
        """
        Calculate the hash of a struct.

        :param type_name: Name of the type.
        :param data: Data defining the struct.
        :return: Hash of the struct.
        """
        return compute_hash_on_elements(
            [self.type_hash(type_name), *self._encode_data(type_name, data)]
        )

    def message_hash(self, account_address: int) -> int:
        message = [
            encode_shortstring("StarkNet Message"),
            self.struct_hash("StarkNetDomain", cast(dict, self.domain)),
            account_address,
            self.struct_hash(self.primary_type, self.message),
        ]

        return compute_hash_on_elements(message)


class Account(StarknetAccount):
    def __init__(
        self,
        *,
        address: AddressRepresentation,
        client: Client,
        signer: Optional[BaseSigner] = None,
        key_pair: Optional[KeyPair] = None,
        chain: Optional[StarknetChainId] = None,
    ):
        super().__init__(
            address=address, client=client, signer=signer, key_pair=key_pair, chain=chain
        )

    def sign_message(self, typed_data: TypedData) -> List[int]:
        typed_data_dataclass = TypedDataDataclass.from_dict(typed_data)
        msg_hash = typed_data_dataclass.message_hash(self.address)
        r, s = message_signature(msg_hash=msg_hash, priv_key=self.signer.key_pair.private_key)
        return [r, s]



def build_auth_message(chainId: int, now: int, expiry: int) -> TypedData:
    message = {
        "message": {
            "method": "POST",
            "path": "/v1/auth",
            "body": "",
            "timestamp": now,
            "expiration": expiry,
        },
        "domain": {"name": "Paradex", "chainId": hex(chainId), "version": "1"},
        "primaryType": "Request",
        "types": {
            "StarkNetDomain": [
                {"name": "name", "type": "felt"},
                {"name": "chainId", "type": "felt"},
                {"name": "version", "type": "felt"},
            ],
            "Request": [
                {"name": "method", "type": "felt"},
                {"name": "path", "type": "felt"},
                {"name": "body", "type": "felt"},
                {"name": "timestamp", "type": "felt"},
                {"name": "expiration", "type": "felt"},
            ],
        },
    }
    return message

def get_account(account_address: str, account_key: str, paradex_config: dict):
    client = FullNodeClient(node_url=paradex_config["starknet_fullnode_rpc_url"])
    key_pair = KeyPair.from_private_key(key=hex_to_int(account_key))
    chain = get_chain_id(paradex_config["starknet_chain_id"])
    account = Account(
        client=client,
        address=account_address,
        key_pair=key_pair,
        chain=chain,
    )
    return account