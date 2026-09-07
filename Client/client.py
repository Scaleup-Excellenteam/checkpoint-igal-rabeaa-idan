"""
TSPO chat client.

Flow:
    1. Ask the user for the server address (or take it from --server).
    2. Authenticate against the REST API (/login or /signup).
    3. Open a WebSocket to /messanger, passing the authenticated
       username as a query parameter so the server can identify the
       session.
    4. Run send/receive loops concurrently. Supports /join, /leave,
       /exit commands; everything else is sent as a chat message in
       the current room.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from urllib.parse import urlencode, urlparse, urlunparse

if sys.platform == "win32":
    os.system("")


try:
    import httpx
    USE_HTTPX = True
except ImportError:
    import requests
    USE_HTTPX = False

import websockets
from websockets.exceptions import ConnectionClosed

DEFAULT_SERVER = "http://172.28.12.20:8000"
WS_PATH = "/messanger"


def parse_args():
    parser = argparse.ArgumentParser(description="TSPO chat client")
    parser.add_argument(
        "--server",
        default=None,
        help=f"Server base URL, e.g. http://172.28.12.20:8000 (default prompts, "
             f"falls back to {DEFAULT_SERVER})",
    )
    return parser.parse_args()


def resolve_server_url(cli_value: str | None) -> str:
    if cli_value:
        return cli_value.rstrip("/")
    entered = input(f"Server address [{DEFAULT_SERVER}]: ").strip()
    return (entered or DEFAULT_SERVER).rstrip("/")


def to_ws_url(http_url: str, username: str) -> str:
    parsed = urlparse(http_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    query = urlencode({"username": username})
    return urlunparse((ws_scheme, parsed.netloc, WS_PATH, "", query, ""))


def _http_post(url: str, json_data: dict) -> tuple[int, dict]:
    """Helper to perform HTTP POST using httpx or requests."""
    if USE_HTTPX:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json=json_data)
            try:
                body = resp.json()
            except Exception:
                body = {"message": resp.text}
            return resp.status_code, body
    else:
        resp = requests.post(url, json=json_data, timeout=10.0)
        try:
            body = resp.json()
        except Exception:
            body = {"message": resp.text}
        return resp.status_code, body


def authenticate(server_url: str) -> str:
    """Interactively login or signup. Returns the authenticated username."""
    while True:
        choice = input("\n[1] Login  [2] Signup: ").strip()
        if choice not in ("1", "2"):
            print("Please enter 1 or 2.")
            continue

        endpoint = "/login" if choice == "1" else "/signup"
        username = input("Username: ").strip()
        password = input("Password: ").strip()

        try:
            status_code, body = _http_post(f"{server_url}{endpoint}", {"username": username, "password": password})
        except Exception as exc:
            print(f"Could not reach server: {exc}")
            if not _retry("Try again?"):
                sys.exit(1)
            continue

        if status_code in (200, 201):
            print(f"\n[SUCCESS] {'Login' if choice == '1' else 'Signup'} successful.")
            return username

        detail = body.get("detail") or body.get("message") or str(body)
        print(f"\n[FAILED] Authentication failed ({status_code}): {detail}")
        if not _retry("Try again?"):
            sys.exit(1)


def _retry(prompt: str) -> bool:
    answer = input(f"{prompt} [Y/N]: ").strip().lower()
    return answer in ("y", "yes")


def print_help_guide():
    print("""
============================================================
              WELCOME TO TSPO CHAT MESSENGER
============================================================
Available Commands:
  /join <room_id>  - Join or switch to a room (e.g., /join general)
  /leave           - Leave the current room
  /list            - View rooms you entered vs other active rooms
  /users           - Show all users and their status (USER - STATUS)
  /help            - Show this command list again
  /exit            - Disconnect and exit the chat application
============================================================
Type /join <room_id> to enter a room and start chatting!
""")


def build_outgoing_payload(current_room: str | None, text: str) -> dict | None:
    """Translate raw CLI input into a structured protocol message."""
    if text == "/help":
        print_help_guide()
        return None

    if text == "/list":
        return {"action": "list"}

    if text == "/users":
        return {"action": "users"}

    if text.startswith("/join "):
        room_id = text[len("/join "):].strip()
        if not room_id:
            print("Usage: /join <room_id>")
            return None
        return {"action": "join", "room": room_id}

    if text == "/leave":
        if not current_room:
            print("You are not currently in any room.")
            return None
        return {"action": "leave", "room": current_room}

    if text == "/exit":
        return {"action": "exit"}

    if not current_room:
        print("You're not in a room yet. Use /join <room_id> first (e.g. /join general). Type /help for commands.")
        return None

    return {"action": "message", "room": current_room, "content": text, "payload": text}


async def receive_messages(ws, state: dict) -> None:
    try:
        async for raw in ws:
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                print(f"\n----- {raw} -----\n# ", end="", flush=True)
                continue

            _render_incoming(payload)
            print("# ", end="", flush=True)
    except ConnectionClosed:
        state["disconnected"] = True


def _render_incoming(payload: dict) -> None:
    action = payload.get("action") or payload.get("type")
    if action == "message":
        print(f"\n[{payload.get('room', '?')}] {payload.get('from', 'unknown')}: "
              f"{payload.get('content', '') or payload.get('payload', '')}")
    elif action in ("joined", "subscribed"):
        print(f"\n----- Joined room '{payload.get('room')}' -----")
    elif action in ("left", "unsubscribed"):
        print(f"\n----- Left room '{payload.get('room', '')}' -----")
    elif action in ("list", "room_list"):
        joined = payload.get("joined_rooms", [])
        others = payload.get("other_rooms", [])
        print("\n================== ROOMS OVERVIEW ==================")
        print("Joined Rooms (You are here):")
        if joined:
            for r in joined:
                print(f"   - {r}")
        else:
            print(" (None - use /join <room_id> to enter a room)")

        print("\nOther Active Rooms on Server:")
        if others:
            for r in others:
                print(f"   - {r}")
        else:
            print(" (No other active rooms)")
        print("====================================================")
    elif action in ("users", "user_list"):
        user_entries = payload.get("users", [])
        print("\n=================== USERS LIST ===================")
        if user_entries:
            for u in user_entries:
                name = u.get("username", "unknown")
                status_val = u.get("status", "OFFLINE")
                print(f"   {name} - {status_val}")
        else:
            print("   (No registered users found)")
        print("==================================================")
    elif action == "error":
        code = payload.get("code")
        message = payload.get("message") or payload.get("error")
        if code == "ACCOUNT_BANNED":
            print(f"\n\033[1;31m===== BANNED: {message} =====\033[0m")
        elif code == "DLP_VIOLATION":
            pass
        else:
            print(f"\n----- Server error: {message} -----")
    else:
        print(f"\n{payload}")


async def send_messages(ws, state: dict) -> None:
    current_room = None
    while True:
        text = await asyncio.to_thread(input, "# ")
        if not text:
            continue

        payload = build_outgoing_payload(current_room, text)
        if payload is None:
            continue

        if payload["action"] == "exit":
            await ws.close()
            return

        try:
            await ws.send(json.dumps(payload))
        except ConnectionClosed:
            state["disconnected"] = True
            return

        if payload["action"] == "join":
            current_room = payload["room"]
        elif payload["action"] == "leave":
            current_room = None


async def run_chat(ws_url: str) -> None:
    state = {"disconnected": False}
    try:
        async with websockets.connect(ws_url) as ws:
            print_help_guide()
            await asyncio.gather(
                receive_messages(ws, state),
                send_messages(ws, state),
            )
    except (ConnectionClosed, OSError) as exc:
        print(f"\n----- Connection lost: {exc} -----")
        return

    if state["disconnected"]:
        print("\n----- Disconnected from server -----")



def main():
    args = parse_args()
    server_url = resolve_server_url(args.server)
    username = authenticate(server_url)
    ws_url = to_ws_url(server_url, username)
    asyncio.run(run_chat(ws_url))


if __name__ == "__main__":
    main()
