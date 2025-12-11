import websocket
import json

websocket_url = "wss://ws.api.prod.paradex.trade/v1"

# Define the message to send
auth = {
  "jsonrpc": "2.0",
  "method": "auth",
  "params": {
    "bearer": "JWcgwMbK0bx1uFFef0Lri35ZDwypmCG0isuBv"
  },
  "id": 0
}
message = {
  "jsonrpc": "2.0",
  "method": "subscribe",
  "params": {
    "channel": "trades.PAXG-USD-PERP"
  },
  "id": 1
}
# message = {
#   "jsonrpc": "2.0",
#   "method": "subscribe",
#   "params": {
#     "channel": "order_book.PAXG-USD-PERP.snapshot@15@50ms@0_01"
#   },
#   "id": 1
# }
# Define a callback to check connection success
def on_open(ws):
    # Auth first
    ws.send(json.dumps(auth))
    # Send the message
    ws.send(json.dumps(message))

# Define a callback to handle the response
def on_message(ws, message):
    response = json.loads(message)
    print(response)

# Connect to the WebSocket server
ws = websocket.WebSocketApp(websocket_url, on_open=on_open, on_message=on_message)

# Wait for a response
ws.run_forever()
