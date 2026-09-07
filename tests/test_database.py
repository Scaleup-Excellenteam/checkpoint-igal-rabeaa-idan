import unittest
import time
from Server.database import (
    init_relational_db,
    db_insert_user,
    get_user_hash,
    get_all_users,
    init_kv_store,
    save_message,
    get_recent_messages
)


class DatabaseStorageTests(unittest.TestCase):
    def setUp(self):
        init_relational_db()
        init_kv_store()

    def test_database_idempotent_initialization(self):
        """Calling init_relational_db and init_kv_store multiple times does not raise errors."""
        init_relational_db()
        init_relational_db()
        init_kv_store()
        init_kv_store()

    def test_db_insert_user_and_get_user_hash(self):
        """Test inserting user and fetching password hash."""
        user = f"db_user_{int(time.time() * 1000)}"
        pw_hash = "mock_salt$mock_hash_xyz"

        self.assertTrue(db_insert_user(user, pw_hash))
        self.assertFalse(db_insert_user(user, pw_hash))  # Duplicate reject

        fetched_hash = get_user_hash(user)
        self.assertEqual(fetched_hash, pw_hash)

        # Non-existent user
        self.assertIsNone(get_user_hash("non_existent_username_000"))

    def test_get_all_users_returns_sorted_list(self):
        """Test that get_all_users retrieves a sorted list of registered usernames."""
        u1 = "z_alpha_test_user"
        u2 = "a_alpha_test_user"
        db_insert_user(u1, "hash1")
        db_insert_user(u2, "hash2")

        all_users = get_all_users()
        self.assertIn(u1, all_users)
        self.assertIn(u2, all_users)
        # Check alphabetical sorting
        self.assertEqual(all_users, sorted(all_users))

    def test_kv_store_save_and_retrieve_recent_messages(self):
        """Test saving messages to KV store and retrieving in chronological order."""
        channel = f"room_kv_test_{int(time.time() * 1000)}"

        save_message("m1", channel, "First message", "2026-09-07 10:00:01")
        save_message("m2", channel, "Second message", "2026-09-07 10:00:02")
        save_message("m3", channel, "Third message", "2026-09-07 10:00:03")

        messages = get_recent_messages(channel, limit=10)
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0]["content"], "First message")
        self.assertEqual(messages[1]["content"], "Second message")
        self.assertEqual(messages[2]["content"], "Third message")

    def test_kv_store_history_limit(self):
        """Test that get_recent_messages respects the limit parameter."""
        channel = f"room_kv_limit_{int(time.time() * 1000)}"

        for i in range(10):
            save_message(f"msg_{i}", channel, f"Text {i}", f"2026-09-07 10:00:{i:02d}")

        recent_3 = get_recent_messages(channel, limit=3)
        self.assertEqual(len(recent_3), 3)
        self.assertEqual(recent_3[-1]["content"], "Text 9")

    def test_risk_score_and_ban_lifecycle(self):
        """Test incrementing risk score and automated banning at threshold."""
        import uuid
        from Server.database import get_user_risk_info, increment_risk_score, is_user_blocked, RISK_SCORE_BAN_THRESHOLD

        test_user = f"risk_user_{uuid.uuid4().hex[:6]}"
        db_insert_user(test_user, "hash123")

        # Initial clean state
        score, blocked = get_user_risk_info(test_user)
        self.assertEqual(score, 0)
        self.assertFalse(blocked)
        self.assertFalse(is_user_blocked(test_user))

        # Strike 1
        s1, b1 = increment_risk_score(test_user, points=1)
        self.assertEqual(s1, 1)
        self.assertFalse(b1)

        # Strike 2
        s2, b2 = increment_risk_score(test_user, points=1)
        self.assertEqual(s2, 2)
        self.assertFalse(b2)

        # Strike 3 (Threshold reached -> Banned)
        s3, b3 = increment_risk_score(test_user, points=1)
        self.assertEqual(s3, 3)
        self.assertTrue(b3)
        self.assertTrue(is_user_blocked(test_user))


if __name__ == "__main__":
    unittest.main()

