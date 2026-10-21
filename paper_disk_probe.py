"""Safe one-time SQLite read/write probe for Render's persistent paper database.

Only creates an internal marker table. It does not create trades, simulate
fills or change existing paper positions. No HTTP mutation endpoint is exposed.
"""
import os
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone

from paper_storage import storage_health

_LOCK = threading.RLock()
_CHECKED = None


def _fail(reason):
    return {
        "write_verified": False,
        "retained_from_previous_process": False,
        "retained_across_code_deploy": False,
        "reason": reason,
    }


def probe_database():
    """Once per Python worker, commit and re-read a harmless disk marker."""
    global _CHECKED
    with _LOCK:
        if _CHECKED is not None:
            return dict(_CHECKED)
        health = storage_health()
        if not health["ready"]:
            return _fail(health["reason"])

        path = os.environ["AUTO_PAPER_DB_PATH"]
        now = datetime.now(timezone.utc).isoformat()
        revision = os.environ.get("RENDER_GIT_COMMIT", "").strip()
        marker = None
        previously_seen = False
        new_revision = False
        try:
            with closing(sqlite3.connect(path, timeout=5)) as conn:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS stockradar_disk_probe (
                            id INTEGER PRIMARY KEY CHECK (id = 1),
                            marker TEXT NOT NULL,
                            first_seen TEXT NOT NULL,
                            last_revision TEXT NOT NULL DEFAULT '',
                            observed_processes INTEGER NOT NULL DEFAULT 1
                        )
                    """)
                    row = conn.execute(
                        "SELECT marker, last_revision FROM stockradar_disk_probe WHERE id=1"
                    ).fetchone()
                    if row is None:
                        marker = secrets.token_hex(16)
                        conn.execute(
                            "INSERT INTO stockradar_disk_probe "
                            "(id, marker, first_seen, last_revision) VALUES (1,?,?,?)",
                            (marker, now, revision),
                        )
                    else:
                        marker = row[0]
                        previously_seen = True
                        new_revision = bool(revision and row[1] and revision != row[1])
                        conn.execute(
                            "UPDATE stockradar_disk_probe "
                            "SET last_revision=?,observed_processes=observed_processes+1 "
                            "WHERE id=1",
                            (revision,),
                        )
            # Reopen from disk; detecting a mount alone is not enough.
            with closing(sqlite3.connect(path, timeout=5)) as read_conn:
                row = read_conn.execute(
                    "SELECT marker FROM stockradar_disk_probe WHERE id=1"
                ).fetchone()
                integrity = read_conn.execute("PRAGMA quick_check").fetchone()
                if row is None or row[0] != marker or integrity != ("ok",):
                    raise sqlite3.DatabaseError("probe_integrity_failed")
        except (sqlite3.Error, OSError, RuntimeError) as exc:
            result = _fail("sqlite_probe_" + type(exc).__name__)
            print("[StockRadar Paper Storage] write_verified=False", flush=True)
            return result

        _CHECKED = {
            "write_verified": True,
            "retained_from_previous_process": previously_seen,
            "retained_across_code_deploy": new_revision,
            "reason": "sqlite_read_write_verified",
        }
        print(
            "[StockRadar Paper Storage] write_verified=True "
            "retained_from_previous_process=" + str(previously_seen) +
            " retained_across_code_deploy=" + str(new_revision),
            flush=True,
        )
        return dict(_CHECKED)
