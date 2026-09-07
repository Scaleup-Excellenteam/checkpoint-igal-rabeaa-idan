import unittest
import json
from Server.validation import (
    parse_client_message,
    MessageValidationError,
    ClientMessage,
    _validate_payload,
    MAX_PAYLOAD_BYTES,
    MAX_NESTING_DEPTH
)


class MessageValidationSecurityTests(unittest.TestCase):
    def test_valid_action_normalization(self):
        """Aliases (join->subscribe, leave->unsubscribe, message->publish) normalize correctly."""
        # join -> subscribe
        m1 = parse_client_message(json.dumps({"action": "join", "room": "lobby"}))
        self.assertEqual(m1.action, "subscribe")
        self.assertEqual(m1.room, "lobby")
        self.assertIsNone(m1.payload)

        # leave -> unsubscribe
        m2 = parse_client_message(json.dumps({"action": "leave", "room": "lobby"}))
        self.assertEqual(m2.action, "unsubscribe")
        self.assertEqual(m2.room, "lobby")
        self.assertIsNone(m2.payload)

        # message -> publish with 'content' alias
        m3 = parse_client_message(json.dumps({"action": "message", "room": "lobby", "content": "hello world"}))
        self.assertEqual(m3.action, "publish")
        self.assertEqual(m3.room, "lobby")
        self.assertEqual(m3.payload, "hello world")

        # default action -> publish
        m4 = parse_client_message(json.dumps({"room": "lobby", "payload": "default action"}))
        self.assertEqual(m4.action, "publish")

    def test_discovery_actions_list_and_users(self):
        """Global discovery actions (list, users) succeed without a room field."""
        m_list = parse_client_message(json.dumps({"action": "list"}))
        self.assertEqual(m_list.action, "list")
        self.assertIsNone(m_list.room)

        m_users = parse_client_message(json.dumps({"action": "users"}))
        self.assertEqual(m_users.action, "users")
        self.assertIsNone(m_users.room)

    def test_room_name_regex_security(self):
        """Room names must be strictly alphanumeric with allowed '.', '_', '-' (1-64 chars)."""
        valid_rooms = ["general", "Room_101", "dev.chat", "room-2", "A", "z" * 64]
        for room in valid_rooms:
            msg = parse_client_message(json.dumps({"action": "subscribe", "room": room}))
            self.assertEqual(msg.room, room)

        invalid_rooms = [
            "../secret",         # Path traversal
            "room/child",        # Directory separator
            "room$name",         # Shell metacharacter
            "room name",         # Spaces
            "-starts-with-dash", # Must start with alphanumeric
            ".starts-with-dot",  # Must start with alphanumeric
            "z" * 65,            # Too long (> 64)
            "",                  # Empty string
            "   ",               # Whitespace only
        ]
        for bad_room in invalid_rooms:
            with self.subTest(bad_room=bad_room), self.assertRaises(MessageValidationError):
                parse_client_message(json.dumps({"action": "subscribe", "room": bad_room}))

    def test_reject_non_json_and_non_dict(self):
        """Reject invalid JSON syntax or non-dict root JSON."""
        bad_inputs = [
            "not json at all",
            "{unquoted_key: 123}",
            "[1, 2, 3]",
            '"just a string"',
            "12345",
            "true",
        ]
        for raw in bad_inputs:
            with self.subTest(raw=raw), self.assertRaises(MessageValidationError):
                parse_client_message(raw)

    def test_reject_non_finite_numbers(self):
        """Reject non-standard JSON constants like NaN, Infinity, -Infinity."""
        for const in ("NaN", "Infinity", "-Infinity"):
            raw = f'{{"room":"general","payload":{const}}}'
            with self.subTest(const=const), self.assertRaises(MessageValidationError):
                parse_client_message(raw)

    def test_reject_null_byte_injection(self):
        """Reject null characters (\x00) in strings and dictionary keys."""
        with self.assertRaises(MessageValidationError):
            _validate_payload("evil\x00string")

        with self.assertRaises(MessageValidationError):
            _validate_payload({"evil\x00key": "val"})

    def test_nesting_depth_limit(self):
        """Reject nested payloads exceeding MAX_NESTING_DEPTH (8)."""
        nested_valid = "data"
        for _ in range(MAX_NESTING_DEPTH):
            nested_valid = {"layer": nested_valid}
        # 8 levels of dict nesting is allowed
        _validate_payload(nested_valid)

        nested_deep = "data"
        for _ in range(MAX_NESTING_DEPTH + 2):
            nested_deep = [nested_deep]
        # > 8 levels should be rejected
        with self.assertRaises(MessageValidationError):
            _validate_payload(nested_deep)

    def test_payload_and_frame_size_limits(self):
        """Reject messages and payloads that exceed size boundaries."""
        # Frame size limit
        huge_raw = json.dumps({"action": "list", "padding": "x" * 25_000})
        with self.assertRaises(MessageValidationError):
            parse_client_message(huge_raw, max_frame_bytes=20_000)

        # Payload size limit
        huge_payload = {"room": "general", "payload": "x" * (MAX_PAYLOAD_BYTES + 100)}
        with self.assertRaises(MessageValidationError):
            parse_client_message(json.dumps(huge_payload))

    def test_subscription_with_payload_rejected(self):
        """Subscribing or unsubscribing with a non-null payload is rejected."""
        with self.assertRaises(MessageValidationError):
            parse_client_message(json.dumps({"action": "subscribe", "room": "general", "payload": "unexpected"}))


if __name__ == "__main__":
    unittest.main()
