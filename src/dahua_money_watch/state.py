from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union


SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_files (
  path TEXT PRIMARY KEY,
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class StateStore:
    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def already_processed(self, path: Path) -> bool:
        stat = path.stat()
        row = self.conn.execute(
            "SELECT 1 FROM processed_files WHERE path = ? AND size = ? AND mtime = ?",
            (str(path), stat.st_size, stat.st_mtime),
        ).fetchone()
        return row is not None

    def mark_processed(self, path: Path) -> None:
        stat = path.stat()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO processed_files(path, size, mtime, processed_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (str(path), stat.st_size, stat.st_mtime),
        )
        self.conn.commit()
