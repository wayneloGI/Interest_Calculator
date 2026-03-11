"""
rate_presets.py — CJ Judgment Interest Rate Lookups
====================================================
Loads the CJ rate table from cj_rates.json and provides lookup functions.

The rate table is a list of {effective_date, rate} entries sorted descending
by date.  A query date maps to the entry with the most recent effective_date
on or before the query date — i.e. the rate that was in force on that day.

Rate values are stored in the JSON as percentages (e.g. 8.107 means 8.107%
per annum) and are returned as Decimal percentages by get_cj_rate_pct(), or
as Decimal fractions (e.g. 0.08107) by get_cj_rate().

Typical usage
-------------
    from rate_presets import get_cj_rate, get_cj_rate_pct, get_rate_table

    rate_fraction = get_cj_rate(date(2025, 6, 15))   # e.g. Decimal("0.08250")
    rate_pct      = get_cj_rate_pct(date(2025, 6, 15)) # e.g. Decimal("8.250")
"""

from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Path resolution — data/cj_rates.json sits two directories above this file
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_HERE, "..", "data")
_RATES_FILE = os.path.join(_DATA_DIR, "cj_rates.json")


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------

class RateEntry(NamedTuple):
    effective_date: date
    rate_pct: Decimal      # percentage, e.g. Decimal("8.107")
    rate: Decimal          # fraction,   e.g. Decimal("0.08107")


# ---------------------------------------------------------------------------
# Loading and caching
# ---------------------------------------------------------------------------

_TABLE: list[RateEntry] | None = None


def _load_table(path: str | None = None) -> list[RateEntry]:
    """
    Load and parse cj_rates.json.  Returns a list sorted descending by
    effective_date (most recent first) so binary search and iteration are
    straightforward.

    Raises FileNotFoundError if the file is missing.
    Raises ValueError if any entry is malformed.
    """
    filepath = path or _RATES_FILE
    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)

    entries: list[RateEntry] = []
    for i, item in enumerate(raw):
        try:
            d = date.fromisoformat(item["effective_date"])
            pct = Decimal(str(item["rate"]))
            entries.append(RateEntry(
                effective_date=d,
                rate_pct=pct,
                rate=pct / Decimal("100"),
            ))
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"cj_rates.json entry {i} is malformed: {item!r}"
            ) from exc

    # Sort descending: index 0 = most recent
    entries.sort(key=lambda e: e.effective_date, reverse=True)
    return entries


def get_rate_table(path: str | None = None) -> list[RateEntry]:
    """
    Return the full rate table.

    When no path is given, result is cached (production use).
    When a custom path is given (tests), always load fresh to ensure isolation.
    """
    global _TABLE
    if path is not None:
        return _load_table(path)
    if _TABLE is None:
        _TABLE = _load_table()
    return _TABLE


def reload_table() -> list[RateEntry]:
    """Force a reload from disk (call after rate_scraper writes new entries)."""
    global _TABLE
    _TABLE = _load_table()
    return _TABLE


# ---------------------------------------------------------------------------
# Lookup functions
# ---------------------------------------------------------------------------

def get_cj_rate(query_date: date, path: str | None = None) -> Decimal:
    """
    Return the CJ judgment interest rate as a **decimal fraction** (e.g.
    Decimal("0.08107") for 8.107% pa) applicable on the given date.

    The applicable rate is the one whose effective_date is the most recent
    date on or before query_date.

    Raises
    ------
    ValueError
        If query_date precedes all entries in the table (i.e. before the
        earliest effective_date on record, currently 1 Jul 2000).
    """
    table = get_rate_table(path)
    for entry in table:              # table is sorted descending
        if entry.effective_date <= query_date:
            return entry.rate
    earliest = table[-1].effective_date
    raise ValueError(
        f"No CJ rate found for {query_date}: the rate table starts from "
        f"{earliest}.  Please check the Judiciary website and update the "
        f"rate table via the Settings page."
    )


def get_cj_rate_pct(query_date: date, path: str | None = None) -> Decimal:
    """
    Same as get_cj_rate() but returns the rate as a **percentage**
    (e.g. Decimal("8.107") for 8.107% pa).
    """
    return get_cj_rate(query_date, path) * Decimal("100")


def get_rate_on_or_after(query_date: date, path: str | None = None) -> RateEntry | None:
    """
    Return the RateEntry whose effective_date is exactly query_date, or the
    next entry that became effective after query_date.  Returns None if no
    such entry exists (query_date is after all entries).

    Useful for the scraper diff: "are there any rates we don't have yet?"
    """
    table = get_rate_table(path)
    # Table is descending; iterate in reverse (ascending) for "on or after"
    for entry in reversed(table):
        if entry.effective_date >= query_date:
            return entry
    return None


def rate_summary(path: str | None = None) -> dict:
    """
    Return a summary dict for the Settings page API response.

    {
        "count": int,
        "earliest_date": "YYYY-MM-DD",
        "latest_date": "YYYY-MM-DD",
        "latest_rate_pct": float,
        "entries": [ {"effective_date": "YYYY-MM-DD", "rate_pct": float}, ... ]
    }
    """
    table = get_rate_table(path)
    return {
        "count": len(table),
        "earliest_date": table[-1].effective_date.isoformat() if table else None,
        "latest_date": table[0].effective_date.isoformat() if table else None,
        "latest_rate_pct": float(table[0].rate_pct) if table else None,
        "entries": [
            {
                "effective_date": e.effective_date.isoformat(),
                "rate_pct": float(e.rate_pct),
            }
            for e in table
        ],
    }
