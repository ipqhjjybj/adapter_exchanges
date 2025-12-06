import json
import asyncio

import lighter
import logging

import json
import websockets

import lighter

from typing import Tuple, Optional
import logging
import json
import websockets
import lighter
import time

def trim_exception(e: Exception) -> str:
    return str(e).strip().split("\n")[-1]


def save_api_key_config(base_url, account_index, private_keys, config_file="./api_key_config.json"):
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump({
            "baseUrl": base_url,
            "accountIndex": account_index,
            "privateKeys": private_keys,
        }, f, ensure_ascii=False, indent=2)


def get_api_key_config(config_file="./api_key_config.json"):
    with open(config_file) as f:
        cfg = json.load(f)

    private_keys_original = cfg["privateKeys"]
    private_key = {}
    for key in private_keys_original.keys():
        private_key[int(key)] = private_keys_original[key]

    return cfg["baseUrl"], cfg["accountIndex"], private_key


def default_example_setup(config_file="./api_key_config.json") -> Optional[Tuple[lighter.SignerClient, lighter.ApiClient, websockets.connect]]:
    logging.basicConfig(level=logging.DEBUG)

    base_url, account_index, private_keys = get_api_key_config(config_file)
    api_client = lighter.ApiClient(configuration=lighter.Configuration(host=base_url))
    client = lighter.SignerClient(
        url=base_url,
        account_index=account_index,
        api_private_keys=private_keys,
    )

    err = client.check_client()
    if err is not None:
        print(f"CheckClient error: {trim_exception(err)}")
        return

    return client, api_client, websockets.connect(f"{base_url.replace('https', 'wss')}/stream")


async def ws_ping(ws_client):
    await ws_client.send(json.dumps({"type": "pong"}))

async def ws_subscribe(ws_client, channel: str, auth: Optional[str] = None):
    if auth is None:
        await ws_client.send(json.dumps({"type": "subscribe", "channel": channel}))
    else:
        await ws_client.send(json.dumps({"type": "subscribe", "channel": channel, "auth": auth}))

async def ws_send_tx(ws_client, tx_type, tx_info, tx_hash):
    # Note: you have the TX Hash from signing the TX
    # You can use this TX Hash to check the status of the TX later on
    # if the server generates a different hash, the signature will fail, so the hash will always be correct
    # because of this, the hash returned by the server will always be the same
    await ws_client.send(
        json.dumps(
            {
                "type": "jsonapi/sendtx",
                "data": {
                    "id": f"my_random_id_{12345678}",  # optional helps id the response
                    "tx_type": tx_type,
                    "tx_info": json.loads(tx_info),
                },
            }
        )
    )

    print(f"expectedHash {tx_hash} response {await ws_client.recv()}")


async def ws_send_batch_tx(ws_client, tx_types, tx_infos, tx_hashes):
    # Note: you have the TX Hash from signing the TX
    # You can use this TX Hash to check the status of the TX later on
    # if the server generates a different hash, the signature will fail, so the hash will always be correct
    # because of this, the hash returned by the server will always be the same
    await ws_client.send(
        json.dumps(
            {
                "type": "jsonapi/sendtxbatch",
                "data": {
                    "id": f"my_random_id_{12345678}",  # optional helps id the response
                    "tx_types": json.dumps(tx_types),
                    "tx_infos": json.dumps(tx_infos),
                },
            }
        )
    )

    print(f"expectedHash {tx_hashes} response {await ws_client.recv()}")



async def main():
    client, api_client, ws_client_promise = default_example_setup()

    # set up WS client and print a connected message
    ws_client: websockets.ClientConnection = await ws_client_promise
    print("Received:", await ws_client.recv())

    # Note: change this to 2048 to trade spot ETH. Make sure you have at least 0.1 ETH to trade spot.
    market_index = 2048

    api_key_index, nonce = client.nonce_manager.next_nonce()
    ask_tx_type, ask_tx_info, ask_tx_hash, error = client.sign_create_order(
        market_index=market_index,
        client_order_index=1001,  # Unique identifier for this order
        base_amount=1000,  # 0.1 ETH
        price=5000_00,  # $5000
        is_ask=True,
        order_type=client.ORDER_TYPE_LIMIT,
        time_in_force=client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
        reduce_only=False,
        trigger_price=0,
        nonce=nonce,
        api_key_index=api_key_index,
    )

    if error is not None:
        print(f"Error signing ask order (first batch): {trim_exception(error)}")
        return

    # intentionally pass api_key_index to the client.nonce_manager so it increases the nonce, without changing the API key.
    # in batch TXs, all TXs must come from the same API key.
    api_key_index, nonce = client.nonce_manager.next_nonce(api_key_index)
    bid_tx_type, bid_tx_info, bid_tx_hash, error = client.sign_create_order(
        market_index=market_index,
        client_order_index=1002,  # Different unique identifier
        base_amount=1000,  # 0.1 ETH
        price=1500_00,  # $1500
        is_ask=False,
        order_type=client.ORDER_TYPE_LIMIT,
        time_in_force=client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
        reduce_only=False,
        trigger_price=0,
        nonce=nonce,
        api_key_index=api_key_index,
    )

    if error is not None:
        print(f"Error signing second order (first batch): {trim_exception(error)}")
        return

    tx_types = [ask_tx_type, bid_tx_type]
    tx_infos = [ask_tx_info, bid_tx_info]
    tx_hashes = [ask_tx_hash, bid_tx_hash]

    await ws_send_batch_tx(ws_client, tx_types, tx_infos, tx_hashes)

    # # In case we want to see the changes in the UI, sleep a bit
    # time.sleep(5)

    # # since this is a new batch, we can request a fresh API key
    # api_key_index, nonce = client.nonce_manager.next_nonce()
    # cancel_tx_type, cancel_tx_info, cancel_tx_hash, error = client.sign_cancel_order(
    #     market_index=market_index,
    #     order_index=1001,  # the index of the order we want cancelled
    #     nonce=nonce,
    #     api_key_index=api_key_index,
    # )

    # if error is not None:
    #     print(f"Error signing first order (second batch): {trim_exception(error)}")
    #     return

    # # intentionally pass api_key_index to the client.nonce_manager so it increases the nonce, without changing the API key.
    # # in batch TXs, all TXs must come from the same API key.
    # api_key_index, nonce = client.nonce_manager.next_nonce(api_key_index)
    # new_ask_tx_type, new_ask_tx_info, new_ask_tx_hash, error = client.sign_create_order(
    #     market_index=market_index,
    #     client_order_index=1003,  # Different unique identifier
    #     base_amount=2000,  # 0.2 ETH
    #     price=5500_00,  # $5500
    #     is_ask=True,
    #     order_type=client.ORDER_TYPE_LIMIT,
    #     time_in_force=client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
    #     reduce_only=False,
    #     trigger_price=0,
    #     nonce=nonce,
    #     api_key_index=api_key_index,
    # )

    # if error is not None:
    #     print(f"Error signing second order (second batch): {trim_exception(error)}")
    #     return

    # tx_types = [cancel_tx_type, new_ask_tx_type]
    # tx_infos = [cancel_tx_info, new_ask_tx_info]
    # tx_hashes = [cancel_tx_hash, new_ask_tx_hash]

    # await ws_send_batch_tx(ws_client, tx_types, tx_infos, tx_hashes)

    # # In case we want to see the changes in the UI, sleep a bit
    # time.sleep(5)

    # # since this is a new batch, we can request a fresh API key
    # api_key_index, nonce = client.nonce_manager.next_nonce()
    # cancel_1_tx_type, cancel_1_tx_info, cancel_1_tx_hash, error = client.sign_cancel_order(
    #     market_index=market_index,
    #     order_index=1002,  # the index of the order we want cancelled
    #     nonce=nonce,
    #     api_key_index=api_key_index,
    # )

    # if error is not None:
    #     print(f"Error signing first order (third batch): {trim_exception(error)}")
    #     return

    # api_key_index, nonce = client.nonce_manager.next_nonce(api_key_index)
    # cancel_2_tx_type, cancel_2_tx_info, cancel_2_tx_hash, error = client.sign_cancel_order(
    #     market_index=market_index,
    #     order_index=1003,  # the index of the order we want cancelled
    #     nonce=nonce,
    #     api_key_index=api_key_index,
    # )

    # if error is not None:
    #     print(f"Error signing second order (third batch): {trim_exception(error)}")
    #     return

    # tx_types = [cancel_1_tx_type, cancel_2_tx_type]
    # tx_infos = [cancel_1_tx_info, cancel_2_tx_info]
    # tx_hashes = [cancel_1_tx_hash, cancel_2_tx_hash]

    # await ws_send_batch_tx(ws_client, tx_types, tx_infos, tx_hashes)


    # # Clean up
    # await client.close()
    # await api_client.close()
    # await ws_client.close()

if __name__ == "__main__":
    asyncio.run(main())
