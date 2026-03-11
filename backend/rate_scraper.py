"""
rate_scraper.py — CJ Rate Scraper
==================================
Fetches the current CJ judgment interest rate table from the HK Judiciary
website and computes a diff against the local cj_rates.json.

Two-step design (matches the Settings page UX):
  1. scrape_rates()  — fetches and parses; returns new entries only (the diff).
                       Does NOT write to disk.
  2. apply_diff()    — writes the diff to cj_rates.json and reloads the cache.

This separation ensures the user can preview changes before they are applied,
protecting the rate data used by saved cases.

Source
------
  https://www.judiciary.hk/en/court_services_facilities/interest_rate.html

The page contains a two-column HTML table:
  | Interest Rates on Judgment debts (% per annum) | Effective Date |
Rows are sorted descending (most recent first) on the page.

Dependencies
------------
  httpx       — HTTP client (sync, no async needed for a manual trigger)
  beautifulsoup4 — HTML parsing

Both are standard pip packages included in requirements.txt.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_HERE, "..", "data")
_RATES_FILE = os.path.join(_DATA_DIR, "cj_rates.json")

_JUDICIARY_URL = (
    "https://www.judiciary.hk/en/court_services_facilities/interest_rate.html"
)

# ---------------------------------------------------------------------------
# Data structure (mirrors RateEntry in rate_presets but with raw strings)
# ---------------------------------------------------------------------------

class ScrapedEntry(NamedTuple):
    effective_date: date
    rate_pct: Decimal   # e.g. Decimal("8.107")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_date(raw: str) -> date:
    """
    Parse a date string from the Judiciary page.
    The page uses the format DD-MM-YYYY (e.g. "01-01-2026").
    Falls back to ISO format YYYY-MM-DD for robustness.
    """
    raw = raw.strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {raw!r}")


def _parse_rate(raw: str) -> Decimal:
    """Parse a rate string like '8.107' or '10.750' into a Decimal."""
    cleaned = raw.strip().replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"Cannot parse rate: {raw!r}")


def parse_judiciary_html(html: str) -> list[ScrapedEntry]:
    """
    Parse the HTML of the Judiciary interest rate page and return a list of
    ScrapedEntry objects sorted descending by effective_date.

    Expects a table with headers containing "Interest Rates" and "Effective Date".
    Raises ValueError if no matching table is found.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise ImportError(
            "beautifulsoup4 is required for the scraper. "
            "Install it with: pip install beautifulsoup4"
        )

    soup = BeautifulSoup(html, "html.parser")
    target_table = None

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        header_text = " ".join(headers).lower()
        if "interest" in header_text and "effective" in header_text:
            target_table = table
            break

    if target_table is None:
        raise ValueError(
            "Could not find the interest rate table on the Judiciary page. "
            "The page structure may have changed — please update the scraper."
        )

    entries: list[ScrapedEntry] = []
    rows = target_table.find_all("tr")

    for row in rows:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 2:
            continue  # header row or empty row

        # Determine which column is rate and which is date
        # The page puts rate first, date second — but we detect dynamically
        # by testing which cell parses as a date (DD-MM-YYYY)
        rate_str, date_str = cells[0], cells[1]
        if re.match(r"\d{2}-\d{2}-\d{4}", cells[1]):
            rate_str, date_str = cells[0], cells[1]
        elif re.match(r"\d{2}-\d{2}-\d{4}", cells[0]):
            date_str, rate_str = cells[0], cells[1]

        try:
            d = _parse_date(date_str)
            r = _parse_rate(rate_str)
        except ValueError:
            continue  # skip unparseable rows silently

        entries.append(ScrapedEntry(effective_date=d, rate_pct=r))

    if not entries:
        raise ValueError(
            "Parsed the interest rate table but found no data rows. "
            "The page structure may have changed."
        )

    entries.sort(key=lambda e: e.effective_date, reverse=True)
    return entries


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------

def compute_diff(
    scraped: list[ScrapedEntry],
    existing_path: str | None = None,
) -> list[ScrapedEntry]:
    """
    Return only the ScrapedEntry objects that are not already in cj_rates.json.

    An entry is considered "already present" if its effective_date already
    appears in the existing file.  The rate value is not compared — if the
    date exists, it is assumed to be correct.
    """
    path = existing_path or _RATES_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing_raw = json.load(f)
        existing_dates = {
            date.fromisoformat(entry["effective_date"])
            for entry in existing_raw
        }
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        existing_dates = set()

    new_entries = [e for e in scraped if e.effective_date not in existing_dates]
    new_entries.sort(key=lambda e: e.effective_date, reverse=True)
    return new_entries


# ---------------------------------------------------------------------------
# Apply diff to disk
# ---------------------------------------------------------------------------

def apply_diff(
    new_entries: list[ScrapedEntry],
    existing_path: str | None = None,
) -> dict:
    """
    Merge new_entries into cj_rates.json, write to disk, and reload the
    in-memory cache in rate_presets.

    Returns a summary dict:
    {
        "applied": int,           # number of new entries written
        "total": int,             # total entries after merge
        "new_dates": ["YYYY-MM-DD", ...]
    }
    """
    if not new_entries:
        return {"applied": 0, "total": _count_existing(existing_path), "new_dates": []}

    path = existing_path or _RATES_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    # Build merged list
    existing_dates = {entry["effective_date"] for entry in existing}
    for entry in new_entries:
        iso = entry.effective_date.isoformat()
        if iso not in existing_dates:
            existing.append({
                "effective_date": iso,
                "rate": float(entry.rate_pct),
            })
            existing_dates.add(iso)

    # Sort descending before writing
    existing.sort(key=lambda e: e["effective_date"], reverse=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    # Reload in-memory cache
    try:
        from rate_presets import reload_table
        reload_table()
    except ImportError:
        pass  # rate_presets may not be importable in all test contexts

    return {
        "applied": len(new_entries),
        "total": len(existing),
        "new_dates": [e.effective_date.isoformat() for e in new_entries],
    }


def _count_existing(path: str | None = None) -> int:
    p = path or _RATES_FILE
    try:
        with open(p, "r", encoding="utf-8") as f:
            return len(json.load(f))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# High-level entry points (called by the FastAPI settings endpoints)
# ---------------------------------------------------------------------------

def scrape_rates(url: str = _JUDICIARY_URL) -> tuple[list[ScrapedEntry], list[ScrapedEntry]]:
    """
    Fetch the Judiciary page, parse it, and return (all_scraped, diff).

    `diff` contains only entries not already in cj_rates.json.

    Raises
    ------
    ImportError  — if httpx or beautifulsoup4 are not installed
    httpx.HTTPError — if the request fails
    ValueError   — if the page cannot be parsed
    """
    try:
        import httpx
    except ImportError:
        raise ImportError(
            "httpx is required for the scraper. "
            "Install it with: pip install httpx"
        )

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()

    all_entries = parse_judiciary_html(response.text)
    diff = compute_diff(all_entries)
    return all_entries, diff


def scrape_from_html(html: str) -> tuple[list[ScrapedEntry], list[ScrapedEntry]]:
    """
    Same as scrape_rates() but accepts pre-fetched HTML.
    Used in tests to avoid real network calls.
    """
    all_entries = parse_judiciary_html(html)
    diff = compute_diff(all_entries)
    return all_entries, diff
