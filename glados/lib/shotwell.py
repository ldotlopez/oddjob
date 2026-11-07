"""Adapter for a Shotwell photo library (its SQLite database), read-only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Shotwell keeps photos and videos in separate tables, keyed by the absolute
# path they were imported from.
MEDIA_TABLES = ("PhotoTable", "VideoTable")


class ShotwellLibrary:
    """Exposure times from a Shotwell library, opened read-only so a running
    Shotwell is neither locked out nor modified."""

    def __init__(self, database: Path) -> None:
        if not database.is_file():
            raise FileNotFoundError(f"Shotwell database not found: {database}")
        self.connection = sqlite3.connect(
            f"{database.absolute().as_uri()}?mode=ro", uri=True
        )

    def close(self) -> None:
        self.connection.close()

    def exposure_time(self, path: Path) -> int | None:
        """The epoch seconds Shotwell recorded for `path`; None if `path` is
        not in the library or has no time (Shotwell stores 0)."""
        candidates = list(dict.fromkeys([str(path.absolute()), str(path.resolve())]))
        try:
            for table in MEDIA_TABLES:
                for candidate in candidates:
                    row = self.connection.execute(
                        f"SELECT exposure_time FROM {table} WHERE filename = ?",
                        (candidate,),
                    ).fetchone()
                    if row is not None and row[0]:
                        return int(row[0])
        except sqlite3.Error as exc:
            raise RuntimeError(f"reading the Shotwell database: {exc}") from exc
        return None
