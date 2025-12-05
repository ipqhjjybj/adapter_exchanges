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


async def ws_ping(ws_client: websockets.ClientConnection):
    await ws_client.send(json.dumps({"type": "pong"}))

async def ws_subscribe(ws_client: websockets.ClientConnection, channel: str, auth: Optional[str] = None):
    if auth is None:
        await ws_client.send(json.dumps({"type": "subscribe", "channel": channel}))
    else:
        await ws_client.send(json.dumps({"type": "subscribe", "channel": channel, "auth": auth}))

async def ws_send_tx(ws_client: websockets.ClientConnection, tx_type, tx_info, tx_hash):
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


async def ws_send_batch_tx(ws_client: websockets.ClientConnection, tx_types, tx_infos, tx_hashes):
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



def default_example_setup(config_file="./api_key_config.json"):
    logging.basicConfig(level=logging.DEBUG)

    base_url, api_key_private_key, account_index, api_key_index = get_api_key_config(config_file)
    print(base_url, api_key_private_key, account_index, api_key_index)
    api_client = lighter.ApiClient(configuration=lighter.Configuration(host=base_url))
    client = lighter.SignerClient(
        url=base_url,
        private_key=api_key_private_key,
        account_index=account_index,
        api_key_index=api_key_index,
    )

    err = client.check_client()
    if err is not None:
        print(f"CheckClient error: {trim_exception(err)}")
        return

    return client, api_client, websockets.connect(f"{base_url.replace('https', 'wss')}/stream")


async def ws_send_tx(ws_client, tx_type, tx_info):
    await ws_client.send(
        json.dumps(
            {
                "type": "jsonapi/sendtx",
                "data": {
                    "id": f"my_random_id_{12345678}",  # optional, helps id the response
                    "tx_type": tx_type,
                    "tx_info": json.loads(tx_info),
                },
            }
        )
    )

    print("Response:", await ws_client.recv())


# this example does the same thing as the create_modify_cancel_order.py example, but sends the TX over WS instead of HTTP
async def main():
    client, api_client, ws_client_promise = default_example_setup()

    # setup WS client and print connected message
    ws_client = await ws_client_promise
    print("Received:", await ws_client.recv())

    # create order
    tx_type, tx_info, err = client.sign_create_order(
        market_index=0,
        client_order_index=123,
        base_amount=1000,  # 0.1 ETH
        price=405000,  # $4050
        is_ask=True,
        order_type=lighter.SignerClient.ORDER_TYPE_LIMIT,
        time_in_force=lighter.SignerClient.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
        reduce_only=False,
        trigger_price=0,
    )
    if err is not None:
        raise Exception(err)
    await ws_send_tx(ws_client, tx_type, tx_info)

    # modify order
    tx_type, tx_info, err = client.sign_modify_order(
        market_index=0,
        order_index=123112,
        base_amount=1100,  # 0.11 ETH
        price=410000,  # $4100
        trigger_price=0,
    )
    if err is not None:
        raise Exception(err)
    await ws_send_tx(ws_client, tx_type, tx_info)

    # cancel order
    tx_type, tx_info, err = client.sign_cancel_order(
        market_index=0,
        order_index=123,
    )
    if err is not None:
        raise Exception(err)
    await ws_send_tx(ws_client, tx_type, tx_info)

    await client.close()
    await api_client.close()
    await ws_client.close()


if __name__ == "__main__":
    asyncio.run(main())
