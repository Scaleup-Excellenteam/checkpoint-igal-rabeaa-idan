"""
Standalone end-to-end verification for the DLP / risk-scoring / ban feature.

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

Run with: python tests/test_dlp_security.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid

import requests
import websockets
from websockets.exceptions import ConnectionClosed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from Server import database as db  # noqa: E402

TEST_PORT = int(os.getenv("DLP_TEST_PORT", "8791"))
TEST_HOST = "127.0.0.1"
BASE_URL = f"http://{TEST_HOST}:{TEST_PORT}"
WS_BASE = f"ws://{TEST_HOST}:{TEST_PORT}/messanger"
ROOM = "lobby"
PASSWORD = "correct-horse-battery"

FAILURES: list[str] = []


def check(condition: bool, description: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


def start_server() -> subprocess.Popen:
    env = os.environ.copy()
    env["SERVER_PORT"] = str(TEST_PORT)
    env["SERVER_HOST"] = TEST_HOST
    proc = subprocess.Popen(
        [sys.executable, "-m", "Server.server"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc


def wait_for_health(timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = requests.get(f"{BASE_URL}/health", timeout=1.0)
            if resp.status_code == 200:
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.3)
    raise RuntimeError("Server did not become healthy in time")


async def recv_json(ws, timeout: float = 5.0) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


async def run_scenario(username: str) -> None:
    ws_url = f"{WS_BASE}?username={username}"

    # ---- 1. Regular message reaches the room ----
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"action": "subscribe", "room": ROOM}))
        joined = await recv_json(ws)
        check(joined.get("action") == "joined", "Subscribed to room successfully")

        await ws.send(json.dumps({"action": "message", "room": ROOM, "content": "hello everyone"}))
        broadcast = await recv_json(ws)
        check(
            broadcast.get("action") == "message" and broadcast.get("content") == "hello everyone",
            "Regular message was broadcast to the room",
        )

        # ---- 2. Strike 1: secret triggers DLP, message dropped ----
        await ws.send(json.dumps({
            "action": "message", "room": ROOM,
            "content": "here is the secret_sauce recipe, don't tell anyone",
        }))
        frame = await recv_json(ws)
        check(frame.get("action") == "error" and frame.get("code") == "DLP_VIOLATION",
              "Strike 1: secret message rejected with DLP_VIOLATION")
        check("1/3" in frame.get("message", ""), "Strike 1: warning reports risk score 1/3")

    score, blocked = db.get_user_risk_info(username)
    check(score == 1 and blocked is False, f"Strike 1 persisted in DB (score={score}, blocked={blocked})")

    # ---- 3. Persistence across reconnect ----
    async with websockets.connect(ws_url) as ws:
        score_after_reconnect, blocked_after_reconnect = db.get_user_risk_info(username)
        check(score_after_reconnect == 1 and not blocked_after_reconnect,
              "Persistence: risk score survives reconnect")

        await ws.send(json.dumps({"action": "subscribe", "room": ROOM}))
        await recv_json(ws)  # joined ack

        # ---- 4. Strike 2 ----
        await ws.send(json.dumps({"action": "message", "room": ROOM, "content": "api_key=SUPERSECRET123"}))
        frame2 = await recv_json(ws)
        check(frame2.get("action") == "error" and frame2.get("code") == "DLP_VIOLATION",
              "Strike 2: credential leak rejected with DLP_VIOLATION")
        check("2/3" in frame2.get("message", ""), "Strike 2: warning reports risk score 2/3")

        # ---- Strike 3: crosses the ban threshold ----
        await ws.send(json.dumps({"action": "message", "room": ROOM, "content": "card: 4111 1111 1111 1111"}))
        frame3 = await recv_json(ws)
        check(frame3.get("action") == "error" and frame3.get("code") == "ACCOUNT_BANNED",
              "Strike 3: credit-card PII triggers ACCOUNT_BANNED")

        closed_with_1008 = False
        try:
            await recv_json(ws)
        except ConnectionClosed as exc:
            closed_with_1008 = getattr(exc, "code", None) == 1008
        check(closed_with_1008, "WebSocket closed with code 1008 after ban")

    score_final, blocked_final = db.get_user_risk_info(username)
    check(score_final == 3 and blocked_final is True,
          f"Ban persisted in DB (score={score_final}, blocked={blocked_final})")

    # ---- 5. Post-ban REST login returns 403 ----
    login_resp = requests.post(f"{BASE_URL}/login", json={"username": username, "password": PASSWORD}, timeout=5)
    check(login_resp.status_code == 403, f"POST /login returns 403 for banned user (got {login_resp.status_code})")

    # ---- 5b. Post-ban WebSocket handshake is also rejected ----
    rejected_at_handshake = False
    try:
        async with websockets.connect(ws_url) as ws:
            try:
                await recv_json(ws, timeout=3.0)
            except ConnectionClosed as exc:
                rejected_at_handshake = getattr(exc, "code", None) == 1008
    except ConnectionClosed as exc:
        rejected_at_handshake = getattr(exc, "code", None) == 1008
    check(rejected_at_handshake, "Fresh WebSocket connection for banned user closed with 1008")


def main() -> None:
    username = f"dlp_test_{uuid.uuid4().hex[:8]}"

    proc = start_server()
    try:
        wait_for_health()

        signup_resp = requests.post(
            f"{BASE_URL}/signup", json={"username": username, "password": PASSWORD}, timeout=5
        )
        check(signup_resp.status_code == 200, f"Test user '{username}' signed up (got {signup_resp.status_code})")

        asyncio.run(run_scenario(username))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All DLP security checks PASSED.")


if __name__ == "__main__":
    main()
