# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scan lifecycle: state, events for the browser, the waiting line, and cleanup.

Everything lives in memory on purpose (no storage volume). See docs/PLAN.md section 6.
"""
import asyncio
import secrets
import time
from collections import deque

from app import config
from app.engine import runner
from app.messages import START_ERRORS


class Busy(Exception):
    """The waiting line is full."""


class Scan:
    def __init__(self, kind: str, start_url: str, scope: str, mode: str, params: dict | None = None,
                 scheme_given: bool = True) -> None:
        self.id = secrets.token_urlsafe(9)
        self.kind = kind  # "scan" or "recheck"
        self.start_url = start_url
        self.scope = scope
        self.mode = mode
        self.params = params or {}
        self.scheme_given = scheme_given
        self.state = "queued"  # queued, running, done, error, cancelled
        self.created = time.monotonic()
        self.finished_at: float | None = None
        self.started: float | None = None
        self.events: list[tuple[int, str, dict]] = []
        self.rows: list[dict] = []
        self._pending_rows: list[dict] = []
        self._row_seq = 0
        self._subs: set[asyncio.Event] = set()
        self.gate = asyncio.Event()
        self.gate.set()
        self.paused = False
        self.cancelled = False
        self.partial_reason: str | None = None
        self.truncated = False
        self.js_notice = False
        self.current = ""
        self.phase = "queued"
        self.profile_data: dict | None = None
        self.host_notes: list = []
        self.error: dict | None = None
        self.stats = {"pages_scanned": 0, "pages_found": 0, "links_found": 0, "links_checked": 0,
                      "ok": 0, "broken": 0, "blocked": 0, "warning": 0, "skipped": 0, "elapsed": 0}
        self._last_progress = None

    # ---------- events ----------
    @property
    def finished(self) -> bool:
        return self.state in ("done", "error", "cancelled")

    def subscribe(self) -> asyncio.Event:
        ev = asyncio.Event()
        self._subs.add(ev)
        return ev

    def unsubscribe(self, ev: asyncio.Event) -> None:
        self._subs.discard(ev)

    def emit(self, type_: str, data: dict) -> None:
        if type_ == "profile":
            self.profile_data = data
        self.events.append((len(self.events) + 1, type_, data))
        for ev in self._subs:
            ev.set()

    def events_after(self, last_id: int) -> list:
        return self.events[last_id:]

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        self.emit("phase", {"phase": phase})

    # ---------- rows ----------
    def add_row(self, row: dict) -> None:
        self._row_seq += 1
        row["id"] = f"r{self._row_seq}"
        self.rows.append(row)
        self._pending_rows.append(row)

    def add_aggregates(self, rows: list[dict]) -> None:
        for row in rows:
            self.add_row(row)

    def remove_targets(self, targets: list[str]) -> None:
        gone = set(targets)
        self.rows = [r for r in self.rows if not (r["bucket"] == "blocked" and r["target"] in gone)]
        self._pending_rows = [r for r in self._pending_rows if not (r["bucket"] == "blocked" and r["target"] in gone)]
        self.emit("rows", {"rows": [], "removeTargets": list(gone)})

    def flush_rows(self) -> None:
        while self._pending_rows:
            chunk, self._pending_rows = self._pending_rows[:400], self._pending_rows[400:]
            self.emit("rows", {"rows": chunk})

    def progress(self) -> dict:
        self.stats["elapsed"] = int(time.monotonic() - (self.started or time.monotonic()))
        return {**self.stats, "phase": self.phase, "current": self.current, "paused": self.paused,
                "truncated": self.truncated}

    def finish_stats(self) -> None:
        self.stats["elapsed"] = int(time.monotonic() - (self.started or time.monotonic()))

    def snapshot(self) -> dict:
        return {"id": self.id, "state": self.state, "kind": self.kind, "url": self.start_url, "scope": self.scope,
                "mode": self.mode, "stats": self.progress(), "profile": self.profile_data, "rows": self.rows,
                "hostNotes": self.host_notes, "partial": bool(self.cancelled), "partialReason": self.partial_reason,
                "truncated": self.truncated, "error": self.error}

    # ---------- control ----------
    def pause(self) -> None:
        self.paused = True
        self.gate.clear()
        self.emit("progress", self.progress())

    def resume(self) -> None:
        self.paused = False
        self.gate.set()
        self.emit("progress", self.progress())

    def cancel(self) -> None:
        self.cancelled = True
        self.gate.set()

    # ---------- run ----------
    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(0.3)
            self.flush_rows()
            snap = self.progress()
            key = tuple(sorted((k, v) for k, v in snap.items() if k != "elapsed"))
            if key != self._last_progress or snap["elapsed"] % 2 == 0:
                self._last_progress = key
                self.emit("progress", snap)

    async def execute(self) -> None:
        self.state = "running"
        self.started = time.monotonic()
        ticker = asyncio.create_task(self._ticker())
        try:
            await runner.run(self)
            self.state = "cancelled" if self.cancelled else "done"
        except runner.StartError as e:
            self.state = "error"
            self.error = {"code": e.code, "message": START_ERRORS.get(e.code, START_ERRORS["error"]), "detail": e.detail}
        except Exception as e:  # last resort, keep the message friendly
            print(f"scan={self.id} failed {type(e).__name__}")
            self.state = "error"
            self.error = {"code": "error", "message": START_ERRORS["error"], "detail": ""}
        finally:
            ticker.cancel()
            self.flush_rows()
            self.finished_at = time.monotonic()
            if self.state == "error":
                self.emit("scan_error", self.error)
            else:
                self.emit("progress", self.progress())
                self.emit("done", {"stats": self.progress(), "partial": bool(self.cancelled),
                                   "partialReason": self.partial_reason or ("stopped" if self.cancelled else None),
                                   "truncated": self.truncated, "hostNotes": self.host_notes})
            self.gate.set()
            for ev in self._subs:
                ev.set()


class Manager:
    def __init__(self) -> None:
        self.scans: dict[str, Scan] = {}
        self.queue: deque[Scan] = deque()
        self.running = 0
        self._purger: asyncio.Task | None = None

    def start(self) -> None:
        self._purger = asyncio.create_task(self._purge_loop())

    def stop(self) -> None:
        if self._purger:
            self._purger.cancel()

    def get(self, scan_id: str) -> Scan | None:
        return self.scans.get(scan_id)

    def submit(self, scan: Scan) -> int:
        """Return 0 if it starts now, or its place in line."""
        cfg = config.CONFIG
        if self.running >= cfg.max_concurrent_scans and len(self.queue) >= cfg.queue_size:
            raise Busy()
        self.scans[scan.id] = scan
        self.queue.append(scan)
        self._start_next()
        return self.position(scan)

    def position(self, scan: Scan) -> int:
        try:
            return list(self.queue).index(scan) + 1
        except ValueError:
            return 0

    def _start_next(self) -> None:
        cfg = config.CONFIG
        while self.queue and self.running < cfg.max_concurrent_scans:
            s = self.queue.popleft()
            if s.cancelled:
                continue
            self.running += 1
            asyncio.create_task(self._run(s))
        for i, s in enumerate(self.queue, start=1):
            s.emit("queue", {"position": i})

    async def _run(self, scan: Scan) -> None:
        try:
            await scan.execute()
        finally:
            self.running -= 1
            self._start_next()

    def cancel(self, scan: Scan) -> None:
        if scan in self.queue:
            self.queue.remove(scan)
            scan.state = "cancelled"
            scan.cancelled = True
            scan.finished_at = time.monotonic()
            scan.emit("done", {"stats": scan.progress(), "partial": True, "partialReason": "stopped",
                               "truncated": False, "hostNotes": []})
            self._start_next()
        else:
            scan.cancel()

    async def _purge_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            ttl = config.CONFIG.results_ttl_seconds
            now = time.monotonic()
            for sid, s in list(self.scans.items()):
                if s.finished_at is not None and now - s.finished_at > ttl:
                    del self.scans[sid]


MANAGER = Manager()
