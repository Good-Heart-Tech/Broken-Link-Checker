# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hands out jobs round-robin across hosts so no single site is hit too hard.

Workers never sit waiting on one busy host: if a host is at its limit, the next host's job goes first.
"""
import asyncio
import time
from collections import deque


class HostScheduler:
    def __init__(self, limit_for, gate: asyncio.Event) -> None:
        self._limit_for = limit_for  # host -> max in flight
        self._gate = gate  # cleared while paused
        self._queues: dict[str, deque] = {}
        self._inflight: dict[str, int] = {}
        self._order: deque = deque()
        self._cond = asyncio.Condition()
        self._pending = 0
        self.closed = False
        self.idle = asyncio.Event()
        self.idle.set()

    @property
    def pending(self) -> int:
        return self._pending

    async def add(self, host: str, job) -> None:
        async with self._cond:
            if self.closed:
                return
            q = self._queues.setdefault(host, deque())
            if not q and host not in self._order:
                self._order.append(host)
            q.append(job)
            self._pending += 1
            self.idle.clear()
            self._cond.notify()

    async def get(self):
        """Next (host, job), or None when closed."""
        while True:
            await self._gate.wait()
            async with self._cond:
                if self.closed:
                    return None
                for _ in range(len(self._order)):
                    host = self._order[0]
                    self._order.rotate(-1)
                    q = self._queues.get(host)
                    if not q:
                        self._order.remove(host)
                        continue
                    if self._inflight.get(host, 0) < self._limit_for(host):
                        self._inflight[host] = self._inflight.get(host, 0) + 1
                        return host, q.popleft()
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout=0.25)
                except asyncio.TimeoutError:
                    pass

    async def done(self, host: str) -> None:
        async with self._cond:
            self._inflight[host] = max(0, self._inflight.get(host, 1) - 1)
            self._pending -= 1
            if self._pending <= 0:
                self.idle.set()
            self._cond.notify_all()

    async def close(self) -> None:
        async with self._cond:
            self.closed = True
            self.idle.set()
            self._cond.notify_all()
