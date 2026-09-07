import asyncio
import json
import unittest
import uuid
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from Server.server import MAX_FRAME_BYTES, websocket_messanger
from Server.database import init_relational_db, init_kv_store, db_insert_user
from Server.auth import hash_password


class WebSocketCommandsTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        init_relational_db()
        init_kv_store()

    async def test_list_command_returns_room_overview(self) -> None:
        """Testing 'list' action returns correct joined and available rooms overview."""
        async with serve(
            websocket_messanger,
            "127.0.0.1",
            0,
            max_size=MAX_FRAME_BYTES,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/messanger"

            async with connect(uri) as ws:
                # Subscribe to general room
                await ws.send(json.dumps({"action": "subscribe", "room": "general_room", "payload": None}))
                ack = json.loads(await ws.recv())
                self.assertEqual(ack.get("type"), "subscribed")

                # Send list command
                await ws.send(json.dumps({"action": "list"}))
                overview = json.loads(await ws.recv())

                self.assertEqual(overview.get("type"), "room_list")
                self.assertIn("general_room", overview.get("joined_rooms", []))
                self.assertIn("general_room", overview.get("all_rooms", []))

    async def test_users_command_distinguishes_online_and_offline(self) -> None:
        """Testing 'users' action accurately reflects online and offline registered users."""
        uid = uuid.uuid4().hex[:6]
        user_online = f"user_on_{uid}"
        user_offline = f"user_off_{uid}"

        # Register users in DB
        db_insert_user(user_online, hash_password("pass123"))
        db_insert_user(user_offline, hash_password("pass123"))

        async with serve(
            websocket_messanger,
            "127.0.0.1",
            0,
            max_size=MAX_FRAME_BYTES,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            # Connect only user_online
            uri = f"ws://127.0.0.1:{port}/messanger?username={user_online}"

            async with connect(uri) as ws:
                # Query user list
                await ws.send(json.dumps({"action": "users"}))
                resp = json.loads(await ws.recv())

                self.assertEqual(resp.get("type"), "user_list")
                users_map = {u["username"]: u["status"] for u in resp.get("users", [])}

                self.assertIn(user_online, users_map)
                self.assertEqual(users_map[user_online], "ONLINE")

                self.assertIn(user_offline, users_map)
                self.assertEqual(users_map[user_offline], "OFFLINE")

    async def test_publishing_without_subscribing_fails(self) -> None:
        """Sending a message to a room without subscribing first receives an error frame."""
        async with serve(
            websocket_messanger,
            "127.0.0.1",
            0,
            max_size=MAX_FRAME_BYTES,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/messanger"

            async with connect(uri) as ws:
                # Attempt publish without subscribe
                await ws.send(json.dumps({"room": "unjoined_room", "payload": "sneak peek"}))
                err = json.loads(await ws.recv())
                self.assertEqual(err.get("type"), "error")
                self.assertIn("subscribe", err.get("message", "").lower())

    async def test_unsubscribe_workflow(self) -> None:
        """Client receives messages after subscribing, but stops receiving after unsubscribing."""
        async with serve(
            websocket_messanger,
            "127.0.0.1",
            0,
            max_size=MAX_FRAME_BYTES,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/messanger"

            async with connect(uri) as client1, connect(uri) as client2:
                # Both subscribe to room
                room = f"test_unsub_{uuid.uuid4().hex[:6]}"
                await client1.send(json.dumps({"action": "subscribe", "room": room, "payload": None}))
                await client2.send(json.dumps({"action": "subscribe", "room": room, "payload": None}))
                await client1.recv()
                await client2.recv()

                # Client 1 unsubscribes
                await client1.send(json.dumps({"action": "unsubscribe", "room": room, "payload": None}))
                unsub_ack = json.loads(await client1.recv())
                self.assertEqual(unsub_ack.get("type"), "unsubscribed")

                # Client 2 publishes
                await client2.send(json.dumps({"room": room, "payload": "message after unsub"}))
                msg2 = json.loads(await client2.recv())
                self.assertEqual(msg2.get("payload"), "message after unsub")

                # Client 1 should NOT receive anything
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(client1.recv(), timeout=0.05)


if __name__ == "__main__":
    unittest.main()
