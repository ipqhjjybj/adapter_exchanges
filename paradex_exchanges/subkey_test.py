"""
Paradex JWT Token 生成示例
演示如何使用 subkey (私钥) 生成 JWT token

认证方式：
1. 主密钥认证: POST /auth - 使用账户私钥
2. Subkey 认证: POST /auth/{public_key} - 使用 subkey 私钥
"""

import time
from enum import IntEnum
from typing import Dict, List, Optional

import requests
from starknet_py.common import int_from_bytes
from starknet_py.net.account.account import Account as StarknetAccount
from starknet_py.net.client import Client
from starknet_py.net.full_node_client import FullNodeClient
from starknet_py.net.models import AddressRepresentation, StarknetChainId
from starknet_py.net.signer import BaseSigner
from starknet_py.net.signer.stark_curve_signer import KeyPair
from starknet_py.utils.typed_data import TypedData as TypedDataDataclass
from starknet_py.hash.utils import message_signature


# ============ 工具函数 ============

def hex_to_int(val: str) -> int:
    """将十六进制字符串转换为整数"""
    return int(val, 16)


def get_chain_id(chain_id: str):
    """获取 StarkNet 链 ID"""
    class CustomStarknetChainId(IntEnum):
        PRIVATE_TESTNET = int_from_bytes(chain_id.encode("UTF-8"))
    return CustomStarknetChainId.PRIVATE_TESTNET


# ============ Account 类 ============

class Account(StarknetAccount):
    """扩展的 Account 类，支持消息签名"""

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

    def sign_message(self, typed_data: dict) -> List[int]:
        """使用私钥签名消息"""
        typed_data_dataclass = TypedDataDataclass.from_dict(typed_data)
        msg_hash = typed_data_dataclass.message_hash(self.address)
        r, s = message_signature(msg_hash=msg_hash, priv_key=self.signer.key_pair.private_key)
        return [r, s]


# ============ 核心函数 ============

def build_auth_message(chain_id: int, now: int, expiry: int) -> dict:
    """构建认证消息（EIP-712 风格的 TypedData）"""
    return {
        "message": {
            "method": "POST",
            "path": "/v1/auth",
            "body": "",
            "timestamp": now,
            "expiration": expiry,
        },
        "domain": {
            "name": "Paradex",
            "chainId": hex(chain_id),
            "version": "1"
        },
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


def get_account(account_address: str, private_key: str, paradex_config: dict) -> Account:
    """创建 Account 对象"""
    client = FullNodeClient(node_url=paradex_config["starknet_fullnode_rpc_url"])
    key_pair = KeyPair.from_private_key(key=hex_to_int(private_key))
    chain = get_chain_id(paradex_config["starknet_chain_id"])
    return Account(
        client=client,
        address=account_address,
        key_pair=key_pair,
        chain=chain,
    )


def get_paradex_config(base_url: str) -> Dict:
    """获取 Paradex 系统配置"""
    print("正在获取 Paradex 系统配置...")
    response = requests.get(base_url + "/system/config", timeout=60)
    if response.status_code != 200:
        raise Exception(f"获取配置失败: {response.text}")
    return response.json()


def get_jwt_token_with_subkey(
    paradex_config: Dict,
    paradex_http_url: str,
    account_address: str,
    subkey_private_key: str,
    subkey_public_key: str,
) -> tuple[str, int]:
    """
    使用 Subkey 生成 JWT token

    Subkey 认证使用 /auth/{public_key} 端点

    Args:
        paradex_config: Paradex 系统配置
        paradex_http_url: API 基础 URL
        account_address: 主账户地址
        subkey_private_key: Subkey 私钥
        subkey_public_key: Subkey 公钥

    Returns:
        (jwt_token, expiry) 元组
    """
    chain_id = int_from_bytes(paradex_config["starknet_chain_id"].encode())
    print(f"链 ID: {chain_id}")

    # 使用 subkey 私钥创建 Account（地址仍然是主账户地址）
    account = get_account(account_address, subkey_private_key, paradex_config)
    print(f"主账户地址: {account_address}")
    print(f"Subkey 公钥: {subkey_public_key}")

    # 构建认证消息
    now = int(time.time())
    expiry = now + 24 * 60 * 60 * 7  # 7 天后过期
    message = build_auth_message(chain_id, now, expiry)
    print(f"消息时间戳: {now}")
    print(f"过期时间: {expiry}")

    # 使用 subkey 私钥签名
    sig = account.sign_message(message)
    print(f"签名 r: {sig[0]}")
    print(f"签名 s: {sig[1]}")

    # 构建请求头
    headers = {
        "PARADEX-STARKNET-ACCOUNT": account_address,
        "PARADEX-STARKNET-SIGNATURE": f'["{sig[0]}","{sig[1]}"]',
        "PARADEX-TIMESTAMP": str(now),
        "PARADEX-SIGNATURE-EXPIRATION": str(expiry),
    }

    # Subkey 认证使用 /auth/{public_key} 端点
    url = f"{paradex_http_url}/auth/{subkey_public_key}"
    print(f"\n发送认证请求到: {url}")

    response = requests.post(url, headers=headers, timeout=60)
    response_json = response.json()

    if response.status_code == 200:
        token = response_json["jwt_token"]
        print(f"\n✓ JWT Token 获取成功!")
        print(f"Token: {token[:50]}...")
        return token, expiry
    else:
        raise Exception(f"获取 JWT 失败: {response_json}")


def get_jwt_token(
    paradex_config: Dict,
    paradex_http_url: str,
    account_address: str,
    private_key: str
) -> tuple[str, int]:
    """
    使用主密钥生成 JWT token

    主密钥认证使用 /auth 端点
    """
    chain_id = int_from_bytes(paradex_config["starknet_chain_id"].encode())
    account = get_account(account_address, private_key, paradex_config)

    now = int(time.time())
    expiry = now + 24 * 60 * 60 * 7
    message = build_auth_message(chain_id, now, expiry)
    sig = account.sign_message(message)

    headers = {
        "PARADEX-STARKNET-ACCOUNT": account_address,
        "PARADEX-STARKNET-SIGNATURE": f'["{sig[0]}","{sig[1]}"]',
        "PARADEX-TIMESTAMP": str(now),
        "PARADEX-SIGNATURE-EXPIRATION": str(expiry),
    }

    # 主密钥认证使用 /auth 端点
    url = f"{paradex_http_url}/auth"
    response = requests.post(url, headers=headers, timeout=60)
    response_json = response.json()

    if response.status_code == 200:
        return response_json["jwt_token"], expiry
    else:
        raise Exception(f"获取 JWT 失败: {response_json}")


# ============ 主程序 ============

if __name__ == "__main__":
    # Paradex API 基础 URL
    BASE_URL = "https://api.prod.paradex.trade/v1"

    # 主账户地址
    ACCOUNT_ADDRESS = "0x58419d41b2986d4f6267ccbb7a53a73bcdd95868771648064eea1d205d56408"

    # Subkey 信息（从 Paradex 网站生成）
    SUBKEY_PRIVATE_KEY = "0x0044ae9b363847e54509e3b3f6ba53b946b78a8ddcc27874feabfc7a0a450bd7"
    SUBKEY_PUBLIC_KEY = "0x7e17ec180717664faeff3f3e907a29f027727ea24e662881442dd5c66c9ed8f"

    print("=" * 60)
    print("Paradex JWT Token 生成演示 (Subkey 模式)")
    print("=" * 60)
    print()

    try:
        # 获取系统配置
        paradex_config = get_paradex_config(BASE_URL)
        print(f"StarkNet 链 ID: {paradex_config['starknet_chain_id']}")
        print()

        # 使用 Subkey 生成 JWT token
        print("=" * 60)
        print("使用 Subkey 生成 JWT Token")
        print("=" * 60)

        jwt_token, expiry = get_jwt_token_with_subkey(
            paradex_config=paradex_config,
            paradex_http_url=BASE_URL,
            account_address=ACCOUNT_ADDRESS,
            subkey_private_key=SUBKEY_PRIVATE_KEY,
            subkey_public_key=SUBKEY_PUBLIC_KEY,
        )

        print()
        print("=" * 60)
        print("JWT Token 生成完成!")
        print("=" * 60)
        print(f"过期时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expiry))}")

        # 使用 JWT token 查询账户
        print()
        print("=" * 60)
        print("使用 JWT Token 查询账户信息")
        print("=" * 60)

        headers = {"Authorization": f"Bearer {jwt_token}"}
        response = requests.get(f"{BASE_URL}/account", headers=headers, timeout=60)

        if response.status_code == 200:
            account_info = response.json()
            print(f"账户余额: {account_info.get('total_collateral', 'N/A')}")
            print("✓ JWT Token 验证成功!")
        else:
            print(f"查询失败: {response.text}")

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()