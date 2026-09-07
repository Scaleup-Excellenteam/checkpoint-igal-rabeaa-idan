"""Validation and sanitization for client WebSocket messages."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Optional

ROOM_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ACTION_ALIASES = {
    "subscribe": "subscribe",
    "join": "subscribe",
    "unsubscribe": "unsubscribe",
    "leave": "unsubscribe",
    "publish": "publish",
    "message": "publish",
    "list": "list",
    "users": "users",
}
ALLOWED_ACTIONS = frozenset(ACTION_ALIASES.keys())
MAX_PAYLOAD_BYTES = 16_384
MAX_NESTING_DEPTH = 8
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
URL_TRAILING_PUNCTUATION = ".,;:!?)]}"


class MessageValidationError(ValueError):
    """A safe-to-display protocol validation error."""


@dataclass(frozen=True)
class ClientMessage:
    action: str
    room: Optional[str]
    payload: Any


def extract_urls(payload: Any) -> tuple[str, ...]:
    """Extract unique HTTP(S) URLs from all string values in a JSON payload."""
    urls: list[str] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, str):
            for match in URL_PATTERN.finditer(value):
                url = match.group(0).rstrip(URL_TRAILING_PUNCTUATION)
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(payload)
    return tuple(urls)


def _validate_payload(value: Any, depth: int = 0) -> None:
    """Reject dangerous/degenerate JSON while leaving user content unchanged."""
    if depth > MAX_NESTING_DEPTH:
        raise MessageValidationError("payload nesting is too deep")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MessageValidationError("payload numbers must be finite")
        return
    if isinstance(value, str):
        if "\x00" in value:
            raise MessageValidationError("payload contains a null character")
        return
    if isinstance(value, list):
        for item in value:
            _validate_payload(item, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or "\x00" in key:
                raise MessageValidationError("payload contains an invalid key")
            _validate_payload(item, depth + 1)
        return
    raise MessageValidationError("payload contains an unsupported value")


def parse_client_message(raw: str, *, max_frame_bytes: int = 20_000) -> ClientMessage:
    """Parse and validate one untrusted JSON text frame."""
    if not isinstance(raw, str):
        raise MessageValidationError("message must be a text frame")
    if len(raw.encode("utf-8")) > max_frame_bytes:
        raise MessageValidationError("message is too large")

    try:
        data = json.loads(
            raw,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid number: {value}")
            ),
        )
    except (ValueError, UnicodeError) as exc:
        raise MessageValidationError("message must be valid JSON") from exc

    if not isinstance(data, dict):
        raise MessageValidationError("message must be a JSON object")

    raw_action = data.get("action", "publish")
    if not isinstance(raw_action, str) or raw_action not in ALLOWED_ACTIONS:
        raise MessageValidationError("action must be subscribe/join, unsubscribe/leave, list, users, or publish")

    normalized_action = ACTION_ALIASES[raw_action]

    # Global discovery commands do not require a room
    if normalized_action in {"list", "users"}:
        return ClientMessage(action=normalized_action, room=data.get("room"), payload=None)

    if "room" not in data:
        raise MessageValidationError("message requires 'room' field")

    room = data["room"]
    if not isinstance(room, str):
        raise MessageValidationError("room must be a string")
    room = room.strip()
    if not ROOM_PATTERN.fullmatch(room):
        raise MessageValidationError(
            "room must be 1-64 characters using letters, numbers, '.', '_' or '-'"
        )

    if normalized_action in {"subscribe", "unsubscribe"}:
        if "payload" in data and data["payload"] is not None:
            raise MessageValidationError("payload must be null for subscription actions")
        payload = None
    else:
        if "payload" not in data and "content" not in data:
            raise MessageValidationError("message requires 'payload' field")
        payload = data.get("payload")
        if payload is None and "content" in data:
            payload = data.get("content")

    if payload is not None:
        _validate_payload(payload)
        serialized_payload = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(serialized_payload) > MAX_PAYLOAD_BYTES:
            raise MessageValidationError("payload is too large")

    return ClientMessage(action=normalized_action, room=room, payload=payload)
