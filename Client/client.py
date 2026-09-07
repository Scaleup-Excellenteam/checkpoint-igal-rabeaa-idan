import asyncio
import json
import os

import websockets
from websockets.exceptions import ConnectionClosed

SERVER_URL = os.getenv("CHAT_SERVER_URL", "ws://127.0.0.1:8000/messanger")


async def send_json(ws, message):
    await ws.send(json.dumps(message, ensure_ascii=False))


async def receive_messages(ws):
    try:
        async for message in ws:
            print(f"\n----- {message} -----")
    except ConnectionClosed:
        print("\n----- Connection closed; you may reconnect safely. -----")


async def send_messages(ws, room):
    while True:
        text = await asyncio.to_thread(input, "# ")

        if text == "/exit":
            await ws.close()
            return

        await send_json(
            ws, {"action": "publish", "room": room, "payload": text}
        )


async def main():
    room = (await asyncio.to_thread(input, "Room: ")).strip()
    async with websockets.connect(SERVER_URL) as ws:
        await send_json(
            ws, {"action": "subscribe", "room": room, "payload": None}
        )
        print("----- Connected to server -----")

        await asyncio.gather(
            receive_messages(ws),
            send_messages(ws, room),
        )


if __name__ == "__main__":
    asyncio.run(main())
