"""Contact form storage.

SQLite via the stdlib `sqlite3` module — no new dependency, and it matches
the direction already flagged as likely for D3BOUUR's config database (see
docs/D3BOUUR_Project_Handoff.md §10). No email sending here; that's an
explicit future step. This just makes sure a submission is never lost.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class ContactStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    message TEXT NOT NULL,
                    submitted_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save(self, name: str, email: str, message: str) -> int:
        submitted_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO submissions (name, email, message, submitted_at) VALUES (?, ?, ?, ?)",
                (name, email, message, submitted_at),
            )
            return cursor.lastrowid

    def all(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT * FROM submissions ORDER BY id DESC").fetchall()
