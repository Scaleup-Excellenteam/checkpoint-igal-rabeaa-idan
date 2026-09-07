import unittest
from Server.auth import hash_password, verify_password, create_user, verify_credentials
from Server.database import init_relational_db


class AuthUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_relational_db()

    def test_hash_password_generates_random_salt(self):
        """Verify that hashing the exact same password twice yields different hashes due to random salt."""
        pwd = "securepassword123"
        hash1 = hash_password(pwd)
        hash2 = hash_password(pwd)
        self.assertNotEqual(hash1, hash2)
        self.assertIn("$", hash1)
        self.assertIn("$", hash2)

    def test_verify_password_correct_and_wrong(self):
        """Verify password validation for matching and non-matching passwords."""
        pwd = "mypassword"
        stored_hash = hash_password(pwd)
        self.assertTrue(verify_password(pwd, stored_hash))
        self.assertFalse(verify_password("wrong_password", stored_hash))
        self.assertFalse(verify_password("", stored_hash))

    def test_verify_password_tampered_hash_fails_gracefully(self):
        """Verify that tampered or malformed hash strings fail gracefully without throwing unhandled exceptions."""
        self.assertFalse(verify_password("pwd", "malformedhashnostringsalt"))
        self.assertFalse(verify_password("pwd", ""))

    def test_create_user_and_verify_credentials(self):
        """Test full user creation and credential verification workflow."""
        import uuid
        uid = uuid.uuid4().hex[:8]
        test_user = f"test_auth_user_{uid}"
        test_pass = "auth_pass_123"

        # Create user
        self.assertTrue(create_user(test_user, test_pass))

        # Duplicate rejection
        self.assertFalse(create_user(test_user, test_pass))

        # Valid credentials
        self.assertTrue(verify_credentials(test_user, test_pass))

        # Invalid credentials
        self.assertFalse(verify_credentials(test_user, "wrong_pass"))
        self.assertFalse(verify_credentials(f"unknown_user_{uid}", test_pass))

    def test_create_user_input_validation(self):
        """Test that short or empty usernames/passwords are rejected."""
        self.assertFalse(create_user("ab", "validpass123"))  # username < 3 chars
        self.assertFalse(create_user("   ", "validpass123"))  # whitespace username
        self.assertFalse(create_user("valid_user_2", "123"))  # password < 4 chars
        self.assertFalse(create_user("valid_user_3", ""))     # empty password


if __name__ == "__main__":
    unittest.main()
