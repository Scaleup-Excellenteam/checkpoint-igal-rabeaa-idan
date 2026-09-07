import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from Server.reputation import URLReputation
from Server.server import MAX_FRAME_BYTES, websocket_messanger


class ServerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @patch("Server.server.VT_API_KEY", "secret")
    @patch("Server.server.check_urls", new_callable=AsyncMock)
    async def test_malicious_url_is_warned_and_not_routed(
        self, check_urls_mock
    ) -> None:
        check_urls_mock.return_value = (
            URLReputation("https://malicious.example", malicious_vendors=3),
        )
        async with serve(websocket_messanger, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/messanger"

            async with connect(uri) as sender, connect(uri) as observer:
                subscription = json.dumps(
                    {"action": "subscribe", "room": "general", "payload": None}
                )
                await sender.send(subscription)
                await observer.send(subscription)
                await sender.recv()
                await observer.recv()

                await sender.send(
                    json.dumps(
                        {"room": "general", "payload": "https://malicious.example"}
                    )
                )

                warning = json.loads(await sender.recv())
                self.assertEqual(warning["type"], "security_warning")
                self.assertIn("3 vendors", warning["error"])
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(observer.recv(), timeout=0.05)

    async def test_network_clients_are_isolated_by_room(self) -> None:
        async with serve(
            websocket_messanger,
            "127.0.0.1",
            0,
            max_size=MAX_FRAME_BYTES,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/messanger"

            async with connect(uri) as general, connect(uri) as games:
                await general.send(
                    json.dumps(
                        {"action": "subscribe", "room": "general", "payload": None}
                    )
                )
                await games.send(
                    json.dumps(
                        {"action": "subscribe", "room": "games", "payload": None}
                    )
                )
                await general.recv()  # subscription acknowledgement
                await games.recv()

                await general.send(
                    json.dumps({"room": "general", "payload": "hello"})
                )

                delivered = json.loads(await general.recv())
                self.assertEqual(delivered["room"], "general")
                self.assertEqual(delivered["payload"], "hello")
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(games.recv(), timeout=0.05)

    async def test_invalid_input_returns_error_and_connection_recovers(self) -> None:
        async with serve(websocket_messanger, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/messanger"

            async with connect(uri) as websocket:
                await websocket.send('{"room":"../admin","payload":"bad"}')
                error = json.loads(await websocket.recv())
                self.assertEqual(error["type"], "error")

                await websocket.send(
                    json.dumps(
                        {"action": "subscribe", "room": "valid", "payload": None}
                    )
                )
                acknowledgement = json.loads(await websocket.recv())
                self.assertEqual(acknowledgement["type"], "subscribed")


if __name__ == "__main__":
    unittest.main()
