"""
FastAPI Entry Point for TSPO Chat Server.
Integrates:
- Relational SQLite Storage & Auth (Teammate 1 - Idan)
- Domain Models & Factory (Teammate 2 - Rabea)
- Observer Pattern & Room Management (Teammate 3 - Igal)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import json
import os
import time
import uuid
from typing import Optional, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from pydantic import BaseModel
import uvicorn

try:
    from Server.database import (
        init_relational_db, init_kv_store, save_message, get_recent_messages,
        is_user_blocked, increment_risk_score,
    )
    from Server.auth import create_user, verify_credentials
    from Server.logger import logger
    from Server.room_manager import RoomManager
    from Server.validation import MessageValidationError, parse_client_message
    from Server.dlp import inspect_dlp
except ImportError:
    from database import (
        init_relational_db, init_kv_store, save_message, get_recent_messages,
        is_user_blocked, increment_risk_score,
    )
    from auth import create_user, verify_credentials
    from logger import logger
    from room_manager import RoomManager
    from validation import MessageValidationError, parse_client_message
    from dlp import inspect_dlp

PORT = int(os.getenv("SERVER_PORT", "8000"))
HOST = os.getenv("SERVER_HOST", "0.0.0.0")
MAX_FRAME_BYTES = 20_000

rooms = RoomManager()


# ==============================================================================
# FASTAPI LIFESPAN (STORAGE INITIALIZATION)
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing relational (users.db) and key-value (messages_kv) storage...")
    init_relational_db()
    init_kv_store()
    logger.info("Storage initialization completed.")
    yield
    logger.info("Server shutting down.")


app = FastAPI(title="TSPO Chat Server", lifespan=lifespan)


# ==============================================================================
# TEAMMATE 1: REST AUTHENTICATION ENDPOINTS
# ==============================================================================

class UserCredentials(BaseModel):
    username: str
    password: str


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"Status": "Healthy"}


@app.post("/signup", status_code=status.HTTP_200_OK)
async def signup_endpoint(credentials: UserCredentials):
    """
    Signup endpoint: creates a new user account with salted password hash.
    Rejects duplicate usernames with HTTP 400.
    """
    created = create_user(credentials.username, credentials.password)
    if not created:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{credentials.username}' is already taken or invalid."
        )
    return {"status": "success", "message": f"User '{credentials.username}' created successfully!"}


@app.post("/login", status_code=status.HTTP_200_OK)
async def login_endpoint(credentials: UserCredentials):
    """
    Login endpoint: verifies user credentials against relational DB.
    Returns HTTP 401 on failure, HTTP 403 if the account is banned.
    """
    if is_user_blocked(credentials.username):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account permanently banned due to security policy violations."
        )

    is_valid = verify_credentials(credentials.username, credentials.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password."
        )
    return {"status": "success", "message": f"Welcome back, {credentials.username}!"}


# ==============================================================================
# TEAMMATE 3: WEBSOCKET ROOM OBSERVER PATTERN & ROUTING
# ==============================================================================

class WebSocketAdapter:
    """Wraps WebSocket or ServerConnection to satisfy the WebSocketObserver Protocol."""
    def __init__(self, ws: Any, username: str = "anonymous"):
        self.ws = ws
        self.username = username

    async def send(self, message: str) -> None:
        if hasattr(self.ws, "send_text"):
            await self.ws.send_text(message)
        else:
            await self.ws.send(message)


async def send_error(ws: Any, message: str) -> None:
    """Send protocol error frame to client."""
    envelope = json.dumps(
        {"action": "error", "type": "error", "message": message, "error": message},
        separators=(",", ":")
    )
    if hasattr(ws, "send_text"):
        await ws.send_text(envelope)
    else:
        await ws.send(envelope)


@app.websocket("/messanger")
async def websocket_messanger(websocket: WebSocket):
    """
    WebSocket endpoint for room-based chat communication.
    Works seamlessly with both FastAPI and standalone websockets serve.
    """
    # Accept connection if it's a FastAPI WebSocket
    if hasattr(websocket, "accept"):
        await websocket.accept()

    # Extract username if available
    username = "anonymous"
    if hasattr(websocket, "query_params"):
        username = websocket.query_params.get("username", "anonymous")
    elif hasattr(websocket, "request") and hasattr(websocket.request, "path"):
        # Check path validity if called via websockets ServerConnection
        if not websocket.request.path.startswith("/messanger"):
            await websocket.close(code=1008, reason="unsupported WebSocket path")
            return

    if username != "anonymous" and is_user_blocked(username):
        logger.warning(f"Rejected WebSocket connection for banned user '{username}'")
        await websocket.close(code=1008, reason="account banned due to security policy violations")
        return

    observer = WebSocketAdapter(websocket, username)
    logger.info(f"WebSocket client connected: user='{username}'")

    try:
        # Loop over incoming messages
        if hasattr(websocket, "receive_text"):
            async def msg_generator():
                while True:
                    yield await websocket.receive_text()
            iterator = msg_generator()
        else:
            iterator = websocket

        async for raw in iterator:
            try:
                msg = parse_client_message(raw, max_frame_bytes=MAX_FRAME_BYTES)
            except MessageValidationError as exc:
                await send_error(websocket, str(exc))
                continue

            if msg.action == "subscribe":
                await rooms.subscribe(msg.room, observer)
                logger.info(f"User '{username}' subscribed to room '{msg.room}'")
                resp = json.dumps(
                    {"action": "joined", "type": "subscribed", "room": msg.room},
                    separators=(",", ":")
                )
                if hasattr(websocket, "send_text"):
                    await websocket.send_text(resp)
                else:
                    await websocket.send(resp)

            elif msg.action == "unsubscribe":
                await rooms.unsubscribe(msg.room, observer)
                logger.info(f"User '{username}' unsubscribed from room '{msg.room}'")
                resp = json.dumps(
                    {"action": "left", "type": "unsubscribed", "room": msg.room},
                    separators=(",", ":")
                )
                if hasattr(websocket, "send_text"):
                    await websocket.send_text(resp)
                else:
                    await websocket.send(resp)

            elif not await rooms.is_subscribed(msg.room, observer):
                await send_error(websocket, "subscribe to the room before publishing")
            else:
                content_str = msg.payload if isinstance(msg.payload, str) else json.dumps(msg.payload)

                is_sensitive, rule_name, reason_code = inspect_dlp(content_str)
                if is_sensitive:
                    new_score, is_blocked = increment_risk_score(username, points=1)
                    logger.warning(
                        f"DLP violation: user='{username}' rule='{rule_name}' "
                        f"reason='{reason_code}' risk_score={new_score} blocked={is_blocked}"
                    )

                    if is_blocked:
                        ban_envelope = json.dumps(
                            {
                                "action": "error",
                                "code": "ACCOUNT_BANNED",
                                "message": "Permanently banned for repeated security/DLP violations.",
                            },
                            separators=(",", ":")
                        )
                        if hasattr(websocket, "send_text"):
                            await websocket.send_text(ban_envelope)
                        else:
                            await websocket.send(ban_envelope)
                        await websocket.close(code=1008, reason="banned for repeated DLP violations")
                        return

                    warn_envelope = json.dumps(
                        {
                            "action": "error",
                            "code": "DLP_VIOLATION",
                            "message": f"DLP violation: {rule_name}. Strike applied. Risk score: {new_score}/3.",
                        },
                        separators=(",", ":")
                    )
                    if hasattr(websocket, "send_text"):
                        await websocket.send_text(warn_envelope)
                    else:
                        await websocket.send(warn_envelope)
                    continue

                timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")
                msg_id = str(uuid.uuid4())

                try:
                    save_message(
                        message_id=msg_id,
                        channel_id=msg.room,
                        content=content_str,
                        timestamp=timestamp_str
                    )
                except Exception as e:
                    logger.error(f"Failed to save message in KV store: {e}")

                envelope = json.dumps(
                    {
                        "action": "message",
                        "type": "message",
                        "room": msg.room,
                        "from": username,
                        "content": content_str,
                        "payload": msg.payload,
                        "timestamp": timestamp_str
                    },
                    ensure_ascii=False,
                    separators=(",", ":")
                )
                await rooms.publish(msg.room, envelope)
                logger.info(f"Broadcast message in room '{msg.room}' from '{username}'")

    except (WebSocketDisconnect, ConnectionError):
        logger.info(f"WebSocket client disconnected: user='{username}'")
    finally:
        # ZOMBIE CLEANUP
        await rooms.remove_observer(observer)


def main():
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
