"""Concurrency-safe Observer pattern implementation for chat rooms."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Protocol, Dict, List

logger = logging.getLogger(__name__)


class WebSocketObserver(Protocol):
    """The operation required from a WebSocket subscriber/observer."""

    async def send(self, message: str) -> None:
        ...


class RoomManager:
    """Subject/Publisher that maintains observers grouped by room.

    The lock protects membership changes. Network I/O is deliberately performed
    after taking a snapshot so a slow client cannot block subscribe/unsubscribe.
    """

    def __init__(self, *, delivery_timeout: float = 5.0) -> None:
        if delivery_timeout <= 0:
            raise ValueError("delivery_timeout must be positive")
        self._rooms: dict[str, set[WebSocketObserver]] = defaultdict(set)
        self._observer_rooms: dict[WebSocketObserver, set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._delivery_timeout = delivery_timeout

    async def subscribe(self, room: str, observer: WebSocketObserver) -> None:
        # OBSERVER PATTERN: attach an observer to this room's publisher.
        async with self._lock:
            self._rooms[room].add(observer)
            self._observer_rooms[observer].add(room)

    async def unsubscribe(self, room: str, observer: WebSocketObserver) -> None:
        # OBSERVER PATTERN: detach an observer from one publisher.
        async with self._lock:
            observers = self._rooms.get(room)
            if observers is not None:
                observers.discard(observer)
                if not observers:
                    self._rooms.pop(room, None)

            subscriptions = self._observer_rooms.get(observer)
            if subscriptions is not None:
                subscriptions.discard(room)
                if not subscriptions:
                    self._observer_rooms.pop(observer, None)

    async def remove_observer(self, observer: WebSocketObserver) -> None:
        """Atomically detach an observer from every room it joined."""
        async with self._lock:
            subscribed_rooms = self._observer_rooms.pop(observer, set())
            for room in subscribed_rooms:
                observers = self._rooms.get(room)
                if observers is None:
                    continue
                observers.discard(observer)
                if not observers:
                    self._rooms.pop(room, None)

    async def is_subscribed(self, room: str, observer: WebSocketObserver) -> bool:
        async with self._lock:
            return observer in self._rooms.get(room, ())

    async def get_rooms_overview(self, observer: WebSocketObserver) -> Dict[str, List[str]]:
        """Returns joined rooms for this observer and other active rooms on the server."""
        async with self._lock:
            joined = sorted(list(self._observer_rooms.get(observer, set())))
            all_rooms = set(self._rooms.keys())
            others = sorted(list(all_rooms - set(joined)))
            return {
                "joined_rooms": joined,
                "other_rooms": others,
                "all_rooms": sorted(list(all_rooms))
            }

    async def publish(self, room: str, message: str) -> int:
        """Notify only this room's observers and return successful send count."""
        async with self._lock:
            # STRICT ROUTING: only observers attached to the requested room are
            # copied. No global connection list is ever broadcast to.
            observers = tuple(self._rooms.get(room, ()))

        if not observers:
            return 0

        results = await asyncio.gather(
            *(
                asyncio.wait_for(
                    observer.send(message), timeout=self._delivery_timeout
                )
                for observer in observers
            ),
            return_exceptions=True,
        )

        failed = [
            observer
            for observer, result in zip(observers, results)
            if isinstance(result, Exception)
        ]
        for observer in failed:
            # ZOMBIE CLEANUP: a failed send marks the socket stale. Remove it
            # from all rooms so future publications remain healthy.
            await self.remove_observer(observer)
            logger.info("Removed unresponsive WebSocket observer from all rooms")

        return len(observers) - len(failed)

    async def room_size(self, room: str) -> int:
        """Return a room's current observer count (useful for metrics/tests)."""
        async with self._lock:
            return len(self._rooms.get(room, ()))
