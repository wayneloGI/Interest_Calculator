"""
case_store.py — SQLite Case Persistence
========================================
CRUD operations for saved cases using stdlib sqlite3.
Zero external dependencies; swap to SQLAlchemy + PostgreSQL later by
re-implementing the same public functions.

Schema
------
  cases
    id              INTEGER PRIMARY KEY AUTOINCREMENT
    name            TEXT NOT NULL
    principal       REAL NOT NULL
    start_date      TEXT NOT NULL   (ISO date YYYY-MM-DD)
    period_count    INTEGER NOT NULL
    total_interest  REAL            (NULL until a calculation is cached)
    request_payload TEXT NOT NULL   (JSON blob of the CalculateRequest)
    last_result     TEXT            (JSON blob of the last CalculateResponse)
    created_at      TEXT NOT NULL   (ISO datetime with UTC offset)
    updated_at      TEXT NOT NULL

Usage
-----
    from case_store import init_db, list_cases, create_case, get_case, update_case, delete_case
    init_db()          # once at startup (idempotent)
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Database path
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DB = os.path.join(_HERE, "..", "data", "cases.db")

# Module-level override used in tests
_DB_PATH: str = _DEFAULT_DB


def _resolve(db_url: str | None) -> str:
    """
    Accept either:
      - None              → use module default (_DB_PATH)
      - "sqlite:///path"  → strip prefix, use path
      - "sqlite:///:memory:" → ":memory:"
      - bare path         → use as-is
    """
    if db_url is None:
        return _DB_PATH
    if db_url.startswith("sqlite:///"):
        return db_url[len("sqlite:///"):]
    return db_url


@contextmanager
def _conn(db_url: str | None):
    path = _resolve(db_url)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS cases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    principal       REAL    NOT NULL,
    start_date      TEXT    NOT NULL,
    period_count    INTEGER NOT NULL,
    total_interest  REAL,
    request_payload TEXT    NOT NULL,
    last_result     TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);
"""


def init_db(db_url: str | None = None) -> None:
    """Create the cases table if it doesn't exist. Idempotent."""
    with _conn(db_url) as con:
        con.executescript(_DDL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_summary(row: sqlite3.Row) -> dict:
    return {
        "id":             row["id"],
        "name":           row["name"],
        "principal":      row["principal"],
        "start_date":     row["start_date"],
        "period_count":   row["period_count"],
        "total_interest": row["total_interest"],
        "created_at":     row["created_at"],
        "updated_at":     row["updated_at"],
    }


def _row_to_detail(row: sqlite3.Row) -> dict:
    d = _row_to_summary(row)
    d["request_payload"] = json.loads(row["request_payload"])
    raw_result = row["last_result"]
    d["last_result"] = json.loads(raw_result) if raw_result else None
    return d


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_cases(db_url: str | None = None) -> list[dict]:
    """Return all cases as summary dicts, most recently updated first."""
    with _conn(db_url) as con:
        rows = con.execute(
            "SELECT * FROM cases ORDER BY updated_at DESC"
        ).fetchall()
    return [_row_to_summary(r) for r in rows]


def get_case(case_id: int, db_url: str | None = None) -> dict | None:
    """Return a single case as a detail dict, or None if not found."""
    with _conn(db_url) as con:
        row = con.execute(
            "SELECT * FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
    return _row_to_detail(row) if row else None


def create_case(
    name: str,
    request_payload: dict,
    db_url: str | None = None,
) -> dict:
    """
    Save a new case. Extracts principal, start_date and period_count from
    the payload for the summary columns.
    """
    principal    = float(request_payload.get("principal", 0))
    start_date   = str(request_payload.get("start_date", ""))
    period_count = len(request_payload.get("periods", []))
    now = _now()

    with _conn(db_url) as con:
        cur = con.execute(
            """INSERT INTO cases
               (name, principal, start_date, period_count,
                total_interest, request_payload, last_result,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, NULL, ?, NULL, ?, ?)""",
            (name, principal, start_date, period_count,
             json.dumps(request_payload), now, now),
        )
        case_id = cur.lastrowid

    return get_case(case_id, db_url)


def update_case(
    case_id: int,
    name: str | None = None,
    request_payload: dict | None = None,
    last_result: dict | None = None,
    db_url: str | None = None,
) -> dict | None:
    """
    Partial update. Any combination of name, request_payload, last_result
    may be supplied; omitted fields are unchanged.

    Returns the updated detail dict, or None if the case doesn't exist.
    """
    if get_case(case_id, db_url) is None:
        return None

    sets: list[str] = ["updated_at = ?"]
    params: list = [_now()]

    if name is not None:
        sets.append("name = ?")
        params.append(name)

    if request_payload is not None:
        sets.append("request_payload = ?")
        params.append(json.dumps(request_payload))
        sets.append("principal = ?")
        params.append(float(request_payload.get("principal", 0)))
        sets.append("start_date = ?")
        params.append(str(request_payload.get("start_date", "")))
        sets.append("period_count = ?")
        params.append(len(request_payload.get("periods", [])))

    if last_result is not None:
        sets.append("last_result = ?")
        params.append(json.dumps(last_result))
        sets.append("total_interest = ?")
        params.append(last_result.get("total_interest"))

    params.append(case_id)

    with _conn(db_url) as con:
        con.execute(
            f"UPDATE cases SET {', '.join(sets)} WHERE id = ?",
            params,
        )

    return get_case(case_id, db_url)


def delete_case(case_id: int, db_url: str | None = None) -> bool:
    """Delete a case. Returns True if it existed, False otherwise."""
    if get_case(case_id, db_url) is None:
        return False
    with _conn(db_url) as con:
        con.execute("DELETE FROM cases WHERE id = ?", (case_id,))
    return True
