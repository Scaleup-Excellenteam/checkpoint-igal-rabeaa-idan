import unittest
from fastapi.testclient import TestClient
from Server.server import app
from Server.database import init_relational_db


class ApiEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_relational_db()
        cls.client = TestClient(app)

    def test_health_endpoint(self):
        """Test GET /health returns HTTP 200 and healthy status."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"Status": "Healthy"})

    def test_signup_and_duplicate_rejection(self):
        """Test user signup succeeds and duplicate registration is rejected with HTTP 400."""
        import uuid
        uid = uuid.uuid4().hex[:8]
        user_payload = {"username": f"api_test_user_{uid}", "password": "api_password_123"}

        # First signup -> 200 OK
        resp1 = self.client.post("/signup", json=user_payload)
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json().get("status"), "success")

        # Duplicate signup -> 400 Bad Request
        resp2 = self.client.post("/signup", json=user_payload)
        self.assertEqual(resp2.status_code, 400)
        self.assertIn("detail", resp2.json())

    def test_login_success_and_failure(self):
        """Test login with valid credentials, invalid password, and unknown username."""
        import uuid
        uid = uuid.uuid4().hex[:8]
        username = f"api_login_user_{uid}"
        signup_payload = {"username": username, "password": "correct_password"}
        self.client.post("/signup", json=signup_payload)

        # Successful login -> 200 OK
        resp_ok = self.client.post("/login", json={"username": username, "password": "correct_password"})
        self.assertEqual(resp_ok.status_code, 200)
        self.assertEqual(resp_ok.json().get("status"), "success")

        # Wrong password -> 401 Unauthorized
        resp_wrong_pwd = self.client.post("/login", json={"username": username, "password": "wrong_password"})
        self.assertEqual(resp_wrong_pwd.status_code, 401)

        # Unknown username -> 401 Unauthorized
        resp_unknown_user = self.client.post("/login", json={"username": f"unknown_ghost_user_{uid}", "password": "any"})
        self.assertEqual(resp_unknown_user.status_code, 401)


if __name__ == "__main__":
    unittest.main()
