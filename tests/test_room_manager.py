import asyncio
import json
import unittest

from Server.room_manager import RoomManager
from Server.validation import MessageValidationError, parse_client_message


class FakeObserver:
    def __init__(self, *, fail: bool = False, delay: float = 0) -> None:
        self.fail = fail
        self.delay = delay
        self.messages: list[str] = []

    async def send(self, data: str) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionError("socket stopped responding")
        self.messages.append(data)


class RoomManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.manager = RoomManager()

    async def test_publish_routes_only_to_requested_room(self) -> None:
        general = FakeObserver()
        games = FakeObserver()
        both = FakeObserver()
        await self.manager.subscribe("general", general)
        await self.manager.subscribe("games", games)
        await self.manager.subscribe("general", both)
        await self.manager.subscribe("games", both)

        sent = await self.manager.publish("general", "hello")

        self.assertEqual(sent, 2)
        self.assertEqual(general.messages, ["hello"])
        self.assertEqual(games.messages, [])
        self.assertEqual(both.messages, ["hello"])

    async def test_failed_observer_is_removed_from_every_room(self) -> None:
        zombie = FakeObserver(fail=True)
        healthy = FakeObserver()
        for room in ("general", "games"):
            await self.manager.subscribe(room, zombie)
        await self.manager.subscribe("general", healthy)

        sent = await self.manager.publish("general", "hello")

        self.assertEqual(sent, 1)
        self.assertEqual(await self.manager.room_size("general"), 1)
        self.assertEqual(await self.manager.room_size("games"), 0)

    async def test_reconnected_client_can_subscribe(self) -> None:
        old_connection = FakeObserver(fail=True)
        new_connection = FakeObserver()
        await self.manager.subscribe("general", old_connection)
        await self.manager.publish("general", "first")
        await self.manager.subscribe("general", new_connection)

        await self.manager.publish("general", "second")

        self.assertEqual(new_connection.messages, ["second"])

    async def test_unresponsive_observer_times_out_and_is_removed(self) -> None:
        manager = RoomManager(delivery_timeout=0.01)
        zombie = FakeObserver(delay=1)
        await manager.subscribe("general", zombie)

        sent = await manager.publish("general", "hello")

        self.assertEqual(sent, 0)
        self.assertEqual(await manager.room_size("general"), 0)


class ValidationTests(unittest.TestCase):
    def test_valid_publish_defaults_action_and_trims_room(self) -> None:
        message = parse_client_message(
            json.dumps({"room": " general ", "payload": {"text": "hello"}})
        )
        self.assertEqual(message.action, "publish")
        self.assertEqual(message.room, "general")

    def test_rejects_malformed_room_and_missing_payload(self) -> None:
        invalid_messages = (
            '{"room":"../admin","payload":"oops"}',
            '{"room":"general"}',
            '[]',
            'not-json',
        )
        for raw in invalid_messages:
            with self.subTest(raw=raw), self.assertRaises(MessageValidationError):
                parse_client_message(raw)

    def test_rejects_oversized_and_deep_payloads(self) -> None:
        with self.assertRaises(MessageValidationError):
            parse_client_message(
                json.dumps({"room": "general", "payload": "x" * 17_000})
            )

        nested = None
        for _ in range(10):
            nested = [nested]
        with self.assertRaises(MessageValidationError):
            parse_client_message(json.dumps({"room": "general", "payload": nested}))

        with self.assertRaises(MessageValidationError):
            parse_client_message('{"room":"general","payload":NaN}')


if __name__ == "__main__":
    unittest.main()
