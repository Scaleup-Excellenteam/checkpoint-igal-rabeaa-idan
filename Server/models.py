"""
Domain models for the TSPO chat server.

Design note - Factory Pattern:
    Client and Room instances are never constructed directly by calling
    code; they are produced by ModelFactory. This keeps object-creation
    logic (validation, defaults, future subclassing by client type or
    room type) in one place. Today the factory methods are thin wrappers,
    but as auth/session state (Teammate 1) and routing rules
    (Teammate 3) grow, the factory is the single seam where those
    concerns can be injected without changing every call site that
    creates a Client or Room.

    Trade-off: for two simple data classes this adds a layer of
    indirection that isn't strictly required yet. We accept that cost
    because three developers are extending this file concurrently, and
    a stable factory interface prevents merge conflicts and divergent
    "new Client()" call sites.
"""

from __future__ import annotations

from typing import Optional


class Client:
    """Represents a single connected chat user."""

    def __init__(self, username: str, websocket=None, risk_score: int = 0, is_blocked: bool = False):
        self.username = username
        self.websocket = websocket
        self.current_room: Optional[str] = None
        self.risk_score = risk_score
        self.is_blocked = is_blocked

    def join_room(self, room_id: str) -> None:
        """Record which room this client currently belongs to."""
        self.current_room = room_id

    def leave_room(self) -> None:
        """Clear the client's current room."""
        self.current_room = None

    async def send(self, payload: dict) -> None:
        """Send a JSON-serializable payload to this client's websocket."""
        if self.websocket is None:
            raise RuntimeError(f"Client '{self.username}' has no active websocket")
        await self.websocket.send_json(payload)

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "room": self.current_room,
            "risk_score": self.risk_score,
            "is_blocked": self.is_blocked,
        }

    def __repr__(self) -> str:
        return (
            f"Client(username={self.username!r}, room={self.current_room!r}, "
            f"risk_score={self.risk_score!r}, is_blocked={self.is_blocked!r})"
        )


class Room:
    """Represents a chat room and the clients subscribed to it."""

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.subscribers: list[Client] = []

    def add_subscriber(self, client: Client) -> None:
        """Add a client to this room if not already present."""
        if client not in self.subscribers:
            self.subscribers.append(client)
            client.join_room(self.room_id)

    def remove_subscriber(self, client: Client) -> None:
        """Remove a client from this room if present."""
        if client in self.subscribers:
            self.subscribers.remove(client)
        if client.current_room == self.room_id:
            client.leave_room()

    def is_empty(self) -> bool:
        return len(self.subscribers) == 0

    async def broadcast(self, payload: dict, exclude: Optional[Client] = None) -> None:
        """Send a payload to every subscriber except `exclude`."""
        for subscriber in self.subscribers:
            if subscriber is exclude:
                continue
            await subscriber.send(payload)

    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "subscribers": [c.username for c in self.subscribers],
        }

    def __repr__(self) -> str:
        names = [c.username for c in self.subscribers]
        return f"Room(room_id={self.room_id!r}, subscribers={names!r})"


class ModelFactory:
    """
    Central creation point for Client and Room instances.

    Using a factory (instead of calling Client()/Room() directly all
    over the codebase) means all three of us can rely on a single,
    stable construction API even while the internals of Client/Room
    evolve independently in this file.
    """

    @staticmethod
    def create_client(username: str, websocket=None, risk_score: int = 0, is_blocked: bool = False) -> Client:
        return Client(username, websocket, risk_score=risk_score, is_blocked=is_blocked)

    @staticmethod
    def create_room(room_id: str) -> Room:
        return Room(room_id)
