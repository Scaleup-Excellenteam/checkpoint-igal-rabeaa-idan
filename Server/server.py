"""WebSocket entry point for the room-based chat server."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

try:  # Supports both ``python -m Server.server`` and ``python Server/server.py``.
    from .reputation import ReputationCheckError, check_urls
    from .room_manager import RoomManager
    from .validation import MessageValidationError, extract_urls, parse_client_message
except ImportError:
    from reputation import ReputationCheckError, check_urls
    from room_manager import RoomManager
    from validation import MessageValidationError, extract_urls, parse_client_message

PORT = 8000
MAX_FRAME_BYTES = 20_000
VT_API_KEY_PLACEHOLDER = "your_virustotal_api_key_here"

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
VT_API_KEY = os.getenv("VT_API_KEY", "").strip()

logger = logging.getLogger(__name__)
rooms = RoomManager()


async def send_error(websocket: ServerConnection, message: str) -> None:
    """Return a protocol error without leaking server implementation details."""
    await websocket.send(
        json.dumps({"type": "error", "error": message}, separators=(",", ":"))
    )


async def send_security_warning(websocket: ServerConnection, message: str) -> None:
    """Tell only the sender that anti-bot filtering rejected the message."""
    await websocket.send(
        json.dumps(
            {"type": "security_warning", "error": message}, separators=(",", ":")
        )
    )


async def url_security_reason(payload: object) -> str | None:
    """Return a blocking reason when a payload URL is malicious or unchecked."""
    urls = extract_urls(payload)
    if not urls:
        return None
    if not VT_API_KEY or VT_API_KEY == VT_API_KEY_PLACEHOLDER:
        raise ReputationCheckError("VT_API_KEY is not configured")

    verdicts = await check_urls(urls, VT_API_KEY)
    for verdict in verdicts:
        if verdict.malicious_vendors > 0:
            return f"URL flagged by {verdict.malicious_vendors} vendors"
    return None


async def websocket_messanger(websocket: ServerConnection) -> None:
    """Process subscription commands and publish validated room messages.

    Wire protocol:
      * ``{"action": "subscribe", "room": "general", "payload": null}``
      * ``{"action": "unsubscribe", "room": "general", "payload": null}``
      * ``{"action": "publish", "room": "general", "payload": "hello"}``

    ``action`` defaults to ``publish``. A client must subscribe before publishing,
    which prevents a connection from injecting messages into arbitrary rooms.
    """
    if websocket.request.path != "/messanger":
        await websocket.close(code=1008, reason="unsupported WebSocket path")
        return

    try:
        async for raw in websocket:
            try:
                message = parse_client_message(raw, max_frame_bytes=MAX_FRAME_BYTES)
            except MessageValidationError as exc:
                await send_error(websocket, str(exc))
                continue

            if message.action == "subscribe":
                await rooms.subscribe(message.room, websocket)
                await websocket.send(
                    json.dumps(
                        {"type": "subscribed", "room": message.room},
                        separators=(",", ":"),
                    )
                )
            elif message.action == "unsubscribe":
                await rooms.unsubscribe(message.room, websocket)
                await websocket.send(
                    json.dumps(
                        {"type": "unsubscribed", "room": message.room},
                        separators=(",", ":"),
                    )
                )
            elif not await rooms.is_subscribed(message.room, websocket):
                await send_error(websocket, "subscribe to the room before publishing")
            else:
                try:
                    blocking_reason = await url_security_reason(message.payload)
                except ReputationCheckError as exc:
                    # Fail closed: unchecked links must not bypass the anti-bot gate.
                    logger.warning(
                        "Security verdict - Verdict: Blocked, Reason: Reputation check unavailable (%s)",
                        exc,
                    )
                    await send_security_warning(
                        websocket,
                        "Message blocked because URL reputation could not be verified",
                    )
                    continue

                if blocking_reason is not None:
                    logger.warning(
                        "Security verdict - Verdict: Blocked, Reason: %s",
                        blocking_reason,
                    )
                    await send_security_warning(
                        websocket, f"Message blocked: {blocking_reason}"
                    )
                    continue

                if extract_urls(message.payload):
                    logger.info(
                        "Security verdict - Verdict: Allowed, Reason: No malicious URL detections"
                    )
                envelope = json.dumps(
                    {
                        "type": "message",
                        "room": message.room,
                        "payload": message.payload,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                await rooms.publish(message.room, envelope)

    except ConnectionClosed:
        logger.info("WebSocket client disconnected")
    finally:
        # ZOMBIE CLEANUP: remove this observer from *every* room regardless of
        # whether the disconnect was orderly, unexpected, or caused by an error.
        await rooms.remove_observer(websocket)


async def run_server() -> None:
    # Ping/pong detects clients that disappear without completing a close
    # handshake. max_size rejects oversized frames before allocating more input.
    async with serve(
        websocket_messanger,
        "0.0.0.0",
        PORT,
        ping_interval=20,
        ping_timeout=20,
        max_size=MAX_FRAME_BYTES,
    ):
        logger.info("Chat server listening on port %d", PORT)
        await asyncio.get_running_loop().create_future()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
