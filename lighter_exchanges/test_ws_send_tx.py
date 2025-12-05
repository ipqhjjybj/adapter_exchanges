import json
import websockets
import asyncio

import lighter
import logging

import json
import websockets

import lighter


def trim_exception(e: Exception) -> str:
    return str(e).strip().split("\n")[-1]


def save_api_key_config(base_url, api_key_private_key, account_index, api_key_index, config_file="./api_key_config.json"):
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump({
            "baseUrl": base_url,
            "apiKeyPrivateKey": api_key_private_key,
            "accountIndex": account_index,
            "apiKeyIndex": api_key_index,
        }, f, ensure_ascii=False, indent=2)


def get_api_key_config(config_file="./api_key_config.json"):
    with open(config_file) as f:
        cfg = json.load(f)

    return cfg["baseUrl"], cfg["apiKeyPrivateKey"], cfg["accountIndex"], cfg["apiKeyIndex"]


def default_example_setup(config_file="./api_key_config.json") -> (lighter.ApiClient, lighter.SignerClient, websockets.ClientConnection):
    logging.basicConfig(level=logging.DEBUG)

    base_url, api_key_private_key, account_index, api_key_index = get_api_key_config(config_file)
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


async def ws_send_tx(ws_client: websockets.ClientConnection, tx_type, tx_info):
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
    ws_client: websockets.ClientConnection = await ws_client_promise
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
