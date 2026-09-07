import unittest
from unittest.mock import AsyncMock
from Server.models import ModelFactory, Client, Room


class ModelFactoryAndDomainTests(unittest.IsolatedAsyncioTestCase):
    def test_factory_creates_client_and_room_instances(self):
        """ModelFactory should create proper Client and Room instances."""
        client = ModelFactory.create_client("alice")
        self.assertIsInstance(client, Client)
        self.assertEqual(client.username, "alice")
        self.assertIsNone(client.current_room)
        self.assertIsNone(client.websocket)

        room = ModelFactory.create_room("general")
        self.assertIsInstance(room, Room)
        self.assertEqual(room.room_id, "general")
        self.assertEqual(room.subscribers, [])

    def test_client_join_and_leave_room(self):
        """Client track current room upon joining and leaving."""
        client = ModelFactory.create_client("bob")
        client.join_room("dev-talk")
        self.assertEqual(client.current_room, "dev-talk")
        self.assertEqual(client.to_dict(), {"username": "bob", "room": "dev-talk"})
        self.assertIn("bob", repr(client))
        self.assertIn("dev-talk", repr(client))

        client.leave_room()
        self.assertIsNone(client.current_room)
        self.assertEqual(client.to_dict(), {"username": "bob", "room": None})

    async def test_client_send_with_and_without_websocket(self):
        """Client.send sends JSON payload via websocket, or raises RuntimeError if none attached."""
        # No websocket attached -> raises RuntimeError
        client_no_ws = ModelFactory.create_client("charlie")
        with self.assertRaises(RuntimeError):
            await client_no_ws.send({"msg": "hello"})

        # Mock websocket attached -> send_json called
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()
        client_with_ws = ModelFactory.create_client("david", websocket=mock_ws)
        payload = {"type": "chat", "text": "hi"}
        await client_with_ws.send(payload)
        mock_ws.send_json.assert_awaited_once_with(payload)

    def test_room_add_and_remove_subscriber(self):
        """Room properly manages subscribers list and prevents duplicate additions."""
        room = ModelFactory.create_room("lobby")
        c1 = ModelFactory.create_client("user1")
        c2 = ModelFactory.create_client("user2")

        self.assertTrue(room.is_empty())

        # Add subscriber
        room.add_subscriber(c1)
        self.assertFalse(room.is_empty())
        self.assertEqual(c1.current_room, "lobby")
        self.assertIn(c1, room.subscribers)

        # Duplicate add should be a no-op
        room.add_subscriber(c1)
        self.assertEqual(len(room.subscribers), 1)

        # Add second subscriber
        room.add_subscriber(c2)
        self.assertEqual(len(room.subscribers), 2)
        self.assertEqual(room.to_dict(), {"room_id": "lobby", "subscribers": ["user1", "user2"]})
        self.assertIn("lobby", repr(room))

        # Remove subscriber
        room.remove_subscriber(c1)
        self.assertNotIn(c1, room.subscribers)
        self.assertIsNone(c1.current_room)
        self.assertEqual(len(room.subscribers), 1)

        # Remove second subscriber -> empty
        room.remove_subscriber(c2)
        self.assertTrue(room.is_empty())

    async def test_room_broadcast_with_and_without_exclude(self):
        """Room broadcast sends to all subscribers, respecting the exclude filter."""
        room = ModelFactory.create_room("announcements")

        ws1 = AsyncMock()
        ws2 = AsyncMock()
        c1 = ModelFactory.create_client("c1", websocket=ws1)
        c2 = ModelFactory.create_client("c2", websocket=ws2)

        room.add_subscriber(c1)
        room.add_subscriber(c2)

        # Broadcast to everyone
        msg1 = {"type": "broadcast", "text": "all"}
        await room.broadcast(msg1)
        ws1.send_json.assert_awaited_with(msg1)
        ws2.send_json.assert_awaited_with(msg1)

        ws1.reset_mock()
        ws2.reset_mock()

        # Broadcast with exclude c1
        msg2 = {"type": "broadcast", "text": "only c2"}
        await room.broadcast(msg2, exclude=c1)
        ws1.send_json.assert_not_awaited()
        ws2.send_json.assert_awaited_once_with(msg2)


if __name__ == "__main__":
    unittest.main()
