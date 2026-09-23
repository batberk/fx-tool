import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

Fetch = Callable[[], Awaitable[Any]]


class TtlCache:
    """Remembers successful answers; failures are never stored.

    Concurrent requests for the same key share a single fetch.
    """

    def __init__(self, max_entries: int = 10_000, clock: Callable[[], float] = time.monotonic) -> None:
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[Hashable, tuple[float | None, Any]] = OrderedDict()
        self._in_flight: dict[Hashable, asyncio.Task] = {}

    async def get_or_fetch(self, key: Hashable, fetch: Fetch, ttl_seconds: float | None) -> Any:
        """Return the cached value, or fetch and keep it (forever when ttl_seconds is None)."""
        found, value = self._lookup(key)
        if found:
            return value

        task = self._in_flight.get(key)
        if task is None:
            task = asyncio.ensure_future(fetch())
            self._in_flight[key] = task
            task.add_done_callback(lambda done: self._finish(key, done, ttl_seconds))
        # shield: one caller disconnecting must not cancel the fetch the others wait on.
        return await asyncio.shield(task)

    def _lookup(self, key: Hashable) -> tuple[bool, Any]:
        entry = self._entries.get(key)
        if entry is None:
            return False, None
        expires_at, value = entry
        if expires_at is not None and self._clock() >= expires_at:
            del self._entries[key]
            return False, None
        self._entries.move_to_end(key)
        return True, value

    def _finish(self, key: Hashable, task: asyncio.Task, ttl_seconds: float | None) -> None:
        del self._in_flight[key]
        if task.cancelled() or task.exception() is not None:
            return
        expires_at = None if ttl_seconds is None else self._clock() + ttl_seconds
        self._entries[key] = (expires_at, task.result())
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
