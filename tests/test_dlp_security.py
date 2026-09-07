"""
End-to-end verification for the DLP / risk-scoring / ban feature.

Spins up the real FastAPI server (Server/server.py) as a subprocess on a
dedicated test port, then drives it over real HTTP + WebSocket connections
to verify:

  1. A normal message reaches the room.
  2. Strike 1: a DLP-sensitive message is dropped, risk_score -> 1, a
     DLP_VIOLATION warning frame is sent back.
  3. Persistence: after reconnecting, the DB still reports risk_score == 1.
  4. Strikes 2 & 3: violations accumulate to risk_score == 3, the account is
     banned, and the WebSocket is closed with code 1008.
  5. Post-ban: POST /login returns HTTP 403, and a fresh WebSocket handshake
     for the banned user is also closed with code 1008.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import unittest
import uuid

import requests
import websockets
from websockets.exceptions import ConnectionClosed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from Server import database as db
from Server.dlp import inspect_dlp

TEST_PORT = int(os.getenv("DLP_TEST_PORT", "8791"))
TEST_HOST = "127.0.0.1"
BASE_URL = f"http://{TEST_HOST}:{TEST_PORT}"
WS_BASE = f"ws://{TEST_HOST}:{TEST_PORT}/messanger"
ROOM = "lobby"
PASSWORD = "correct-horse-battery"


class DLPUitTests(unittest.TestCase):
    def test_dlp_regex_rules(self):
        """Unit test DLP regex rules for secrets, credentials, and credit cards."""
        # 1. tspo_secret
        sensitive, rule, _ = inspect_dlp("Check out our secret_sauce recipe")
        self.assertTrue(sensitive)
        self.assertEqual(rule, "tspo_secret")

        # 2. plaintext_credential
        sensitive, rule, _ = inspect_dlp("My config has api_key = ABC123XYZ")
        self.assertTrue(sensitive)
        self.assertEqual(rule, "plaintext_credential")

        # 3. credit_card_pii
        sensitive, rule, _ = inspect_dlp("Pay using 4111-2222-3333-4444 please")
        self.assertTrue(sensitive)
        self.assertEqual(rule, "credit_card_pii")

        # 4. Normal message
        sensitive, rule, _ = inspect_dlp("Hello world! How is everyone doing?")
        self.assertFalse(sensitive)
        self.assertEqual(rule, "")


class DLPEndToEndIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.username = f"dlp_test_{uuid.uuid4().hex[:8]}"
        env = os.environ.copy()
        env["SERVER_PORT"] = str(TEST_PORT)
        env["SERVER_HOST"] = TEST_HOST
        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "Server.server"],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        # Wait for server health
        deadline = time.monotonic() + 15.0
        healthy = False
        while time.monotonic() < deadline:
            try:
                resp = requests.get(f"{BASE_URL}/health", timeout=1.0)
                if resp.status_code == 200:
                    healthy = True
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(0.3)

        if not healthy:
            cls.proc.terminate()
            raise RuntimeError("Server did not become healthy in time")

        # Signup user
        signup_resp = requests.post(
            f"{BASE_URL}/signup",
            json={"username": cls.username, "password": PASSWORD},
            timeout=5,
        )
        if signup_resp.status_code != 200:
            cls.proc.terminate()
            raise RuntimeError(f"Signup failed: {signup_resp.status_code}")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def test_dlp_strikes_and_ban_enforcement_flow(self):
        """Full flow: normal msg -> strike 1 -> reconnect persistence -> strike 2 -> strike 3 ban -> 403 login / 1008 WS reject."""
        asyncio.run(self._async_scenario())

    async def _async_scenario(self):
        ws_url = f"{WS_BASE}?username={self.username}"

        # Helper
        async def recv_json(ws, timeout: float = 5.0) -> dict:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            return json.loads(raw)

        # 1. Regular message reaches the room
        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({"action": "subscribe", "room": ROOM}))
            joined = await recv_json(ws)
            self.assertEqual(joined.get("action"), "joined")

            await ws.send(json.dumps({"action": "message", "room": ROOM, "content": "hello everyone"}))
            broadcast = await recv_json(ws)
            self.assertEqual(broadcast.get("action"), "message")
            self.assertEqual(broadcast.get("content"), "hello everyone")

            # 2. Strike 1: secret triggers DLP
            await ws.send(json.dumps({
                "action": "message", "room": ROOM,
                "content": "here is the secret_sauce recipe, don't tell anyone",
            }))
            frame = await recv_json(ws)
            self.assertEqual(frame.get("action"), "error")
            self.assertEqual(frame.get("code"), "DLP_VIOLATION")
            self.assertIn("1/3", frame.get("message", ""))

        score, blocked = db.get_user_risk_info(self.username)
        self.assertEqual(score, 1)
        self.assertFalse(blocked)

        # 3. Persistence across reconnect
        async with websockets.connect(ws_url) as ws:
            score_rec, blocked_rec = db.get_user_risk_info(self.username)
            self.assertEqual(score_rec, 1)
            self.assertFalse(blocked_rec)

            await ws.send(json.dumps({"action": "subscribe", "room": ROOM}))
            await recv_json(ws)

            # 4. Strike 2
            await ws.send(json.dumps({"action": "message", "room": ROOM, "content": "api_key=SUPERSECRET123"}))
            frame2 = await recv_json(ws)
            self.assertEqual(frame2.get("action"), "error")
            self.assertEqual(frame2.get("code"), "DLP_VIOLATION")
            self.assertIn("2/3", frame2.get("message", ""))

            # Strike 3: Ban
            await ws.send(json.dumps({"action": "message", "room": ROOM, "content": "card: 4111 1111 1111 1111"}))
            frame3 = await recv_json(ws)
            self.assertEqual(frame3.get("action"), "error")
            self.assertEqual(frame3.get("code"), "ACCOUNT_BANNED")

            closed_with_1008 = False
            try:
                await recv_json(ws)
            except ConnectionClosed as exc:
                closed_with_1008 = getattr(exc, "code", None) == 1008
            self.assertTrue(closed_with_1008)

        score_final, blocked_final = db.get_user_risk_info(self.username)
        self.assertEqual(score_final, 3)
        self.assertTrue(blocked_final)

        # 5. Post-ban REST login returns 403
        login_resp = requests.post(f"{BASE_URL}/login", json={"username": self.username, "password": PASSWORD}, timeout=5)
        self.assertEqual(login_resp.status_code, 403)

        # 5b. Post-ban WebSocket handshake rejected with 1008
        rejected_at_handshake = False
        try:
            async with websockets.connect(ws_url) as ws:
                try:
                    await recv_json(ws, timeout=3.0)
                except ConnectionClosed as exc:
                    rejected_at_handshake = getattr(exc, "code", None) == 1008
        except ConnectionClosed as exc:
            rejected_at_handshake = getattr(exc, "code", None) == 1008
        self.assertTrue(rejected_at_handshake)


if __name__ == "__main__":
    unittest.main()
