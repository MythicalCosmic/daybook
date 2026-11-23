"""What the agent could not send yet: minute stats and alert events, kept on disk (SQLite) for up
to 7 days so nothing is lost while the pharmacy's internet is down."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

KEEP_S = 7 * 86400


class Outbox:
    def __init__(self, path: Path | str, *, keep_s: float = KEEP_S) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.keep_s = keep_s
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS items ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " kind TEXT NOT NULL,"
            " created REAL NOT NULL,"
            " body TEXT NOT NULL,"
            " blob BLOB)"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS items_kind ON items (kind, id)")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def put(self, kind: str, body: dict, *, created: float, blob: bytes | None = None) -> int:
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO items (kind, created, body, blob) VALUES (?, ?, ?, ?)",
                (kind, created, json.dumps(body, separators=(",", ":")), blob),
            )
            return int(cursor.lastrowid)

    def put_stats(self, rows: list[dict], *, created: float) -> None:
        with self._lock:
            self._db.executemany(
                "INSERT INTO items (kind, created, body, blob) VALUES ('stats', ?, ?, NULL)",
                [(created, json.dumps(row, separators=(",", ":"))) for row in rows],
            )

    def put_event(self, event: dict, image: bytes | None, *, created: float) -> int:
        return self.put("event", event, created=created, blob=image)

    def peek(self, kind: str, limit: int) -> list[tuple[int, dict, bytes | None]]:
        """The oldest ``limit`` items of a kind, oldest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, body, blob FROM items WHERE kind = ? ORDER BY id LIMIT ?",
                (kind, int(limit)),
            ).fetchall()
        return [(int(i), json.loads(body), blob) for i, body, blob in rows]

    def delete(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            self._db.executemany("DELETE FROM items WHERE id = ?", [(i,) for i in ids])

    def purge(self, now: float) -> int:
        """Drop what is older than 7 days; Daybook would refuse it anyway."""
        with self._lock:
            cursor = self._db.execute("DELETE FROM items WHERE created < ?", (now - self.keep_s,))
            return cursor.rowcount

    def count(self, kind: str | None = None) -> int:
        with self._lock:
            if kind is None:
                return int(self._db.execute("SELECT COUNT(*) FROM items").fetchone()[0])
            return int(
                self._db.execute("SELECT COUNT(*) FROM items WHERE kind = ?", (kind,)).fetchone()[0]
            )
