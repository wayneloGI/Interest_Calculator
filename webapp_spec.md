# Specification: Judgment Interest Calculator — Web Application

**Version:** 0.2
**Date:** 10 March 2026
**Status:** For review

---

## Goal

Build a Python-based web application that ports the spreadsheet judgment interest calculator into a professional, hosted tool usable by solicitors and paralegals. The MVP delivers reliable multi-period interest calculation, CJ rate presets (kept current via a settings scraper), and paste-ready output (narrative explanation + calculation table). Document export (PDF/Word) is a later phase.

---

## A Note on Front-End Architecture: Vanilla JS vs React

**Recommendation: Vanilla JS for MVP; migrate to React only if complexity warrants it.**

React is a powerful framework, but it introduces meaningful overhead for a first-time web app developer:
- A build step is required (`npm`, `webpack` or `vite`), adding tooling complexity before a single line of app logic is written.
- React's component model, JSX syntax, and state management (hooks, context) have a learning curve that is separate from and on top of the Python/FastAPI work.
- Deployment becomes a two-artefact problem: you must build and serve the React bundle as well as the Python API.

For an app of this scope — one page, a form, a results panel, and a chart — **vanilla HTML + JavaScript is genuinely sufficient** and keeps the entire project in Python + simple web files. The front-end can be served directly by FastAPI as static files, meaning there is only one server to run and deploy.

**When to switch to React:** If the app grows to multiple pages (case management dashboard, settings page, admin panel), or if the UI state becomes difficult to manage with plain JS (e.g. deeply nested dynamic forms), then migrating the front-end to React (or a lighter alternative like Vue or HTMX) is a natural next step. The FastAPI back-end does not change at all when this happens — it just serves the React bundle instead of plain HTML.

**Summary:**

| | Vanilla JS (recommended for MVP) | React |
|---|---|---|
| Learning curve | Low — standard web skills | High — JSX, hooks, build tooling |
| Build step | None | Required (npm + vite/webpack) |
| Deployment | Single server (FastAPI serves static files) | Two artefacts (API + built bundle) |
| Suitability for this project | Fully adequate for MVP | Overkill at this stage |
| Future migration path | Easy — swap static files for React bundle | — |

---

## User Stories

> *As a solicitor*, I want to enter the principal, dates, rates, and day-count settings for a multi-period judgment interest scenario and immediately see the total interest, a per-period breakdown table, and a plain-English explanation I can paste into a letter or submission.

> *As a paralegal*, I want to save a named case and reload it later, so that I can update calculations as a matter progresses without re-entering everything.

> *As a fee earner*, I want to click a "CJ Rate" button and have the applicable rate for a given date filled in automatically, rather than looking it up manually.

> *As a firm administrator*, I want a Settings page that checks the Judiciary website for updated CJ rates and applies them, so the rate table stays current without manual maintenance.

---

## Affected Files / Proposed Project Structure

```
/judgment-interest-app
├── backend/
│   ├── main.py                  ← FastAPI app; all API endpoints; serves /static
│   ├── calculator.py            ← Core calculation engine (pure Python, no web deps)
│   ├── rate_presets.py          ← CJ rate table lookups
│   ├── rate_scraper.py          ← Scrapes judiciary.hk and diffs against cj_rates.json
│   ├── case_store.py            ← Save/load/list cases (SQLite via SQLAlchemy)
│   ├── models.py                ← Pydantic request/response schemas
│   └── auth.py                  ← Shared API-key middleware
├── frontend/
│   ├── index.html               ← Main single-page app
│   ├── app.js                   ← Form logic, API calls, result rendering
│   ├── chart.js                 ← Daily accrual chart (Chart.js)
│   ├── settings.html            ← Settings page: rate table viewer + update trigger
│   └── styles.css               ← Professional, law-firm-appropriate styling
├── data/
│   └── cj_rates.json            ← CJ judgment interest rates; updated by scraper
├── tests/
│   ├── test_calculator.py
│   ├── test_rate_presets.py
│   └── test_api.py
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## UI / Visual Design

**Aesthetic:** Clean and professional — white/light-grey background, conservative navy or dark-teal accent, legible typography (system-ui or Inter). No decorative elements. Desktop-primary, usable on a tablet.

**Layout — two-column on desktop:**

```
┌──────────────────────────────────────────────────────────────────┐
│  Header: "Judgment Interest Calculator" | [Cases ▾]  [⚙ Settings]│
├──────────────────────┬───────────────────────────────────────────┤
│  INPUT PANEL  (35%)  │  RESULTS PANEL  (65%)                     │
│                      │                                           │
│  Case name field     │  [Summary | Periods | Chart | Explain]    │
│  ────────────────    │                                           │
│  Global settings     │  (tab content here)                       │
│  ────────────────    │                                           │
│  Period 1            │                                           │
│  Period 2  [+ Add]   │                                           │
│  ────────────────    │                                           │
│  [Calculate]         │                                           │
│  [Save Case]         │                                           │
└──────────────────────┴───────────────────────────────────────────┘
```

**Input panel — Global Settings:**
- Case Name (text, e.g. "Chan v Wong — HCA 123/2024")
- Initial Principal (HKD, formatted with thousands separator)
- Start Date (date picker)
- Day Count Convention (dropdown: Actual/365 Fixed | Anniversary/365 | Actual/Actual)

**Input panel — Period Rows:**

*Always visible:*
- Start Date (auto-filled from previous period's End Date; editable)
- End Date (date picker)
- Rate (numeric) + Rate Basis (dropdown: Per annum / Per month / Per quarter / Per day) + [CJ Rate] button
- Interest Type (Simple / Compound toggle)

*Expanded / advanced (collapsed by default):*
- Interest Basis (Initial Principal / Running Sum)
- Compounding Frequency (shown only when Compound selected)
- Include Start Day / Include End Day (toggles)
- Start Contribution / End Contribution

**CJ Rate button:** Opens a small inline popover: "CJ rate from 1 Jan 2026: **8.107% pa** — Apply?" One click fills the Rate field. If no rate covers the date, shows a warning in amber.

---

## Interaction Details

**Period management:** "+ Add Period" appends a row, pre-filling Start Date from the previous End Date. "×" removes a period (confirm prompt only if data has been entered).

**Calculate:** A prominent primary button triggers POST `/api/calculate`. Results render in the right panel. The button shows a spinner during the request (target: under 200ms).

**Results tabs:**

- **Summary** — Principal, Total Interest, Total Amount, generation date, key settings.
- **Periods** — Table: Period | Start | End | Days | Year Fraction | Rate | Eff. Period Rate | Interest | Cumulative Interest. A "Copy table" button copies it as tab-separated plain text, ready to paste into Word or Excel.
- **Chart** — Stacked area chart on a daily x-axis with three series: Principal (flat) | Prior Cumulative Interest | Current Period Accrual. Hover tooltip shows date and amounts. Simple-interest periods show linear growth; compound periods show exponential curves.
- **Explain** — One plain-English paragraph per period (matching the spreadsheet's Explanation sheet style), followed by a summary sentence. A "Copy all" button copies the full text to clipboard.

**Save / Load cases:**
- "Save Case" stores all inputs under the case name. If a case with that name already exists: "Update existing case?"
- The "Cases ▾" header dropdown lists saved cases, most-recently-modified first, with a search box. Selecting one restores all inputs.

**Settings page (`settings.html`):**
- Read-only table of the current CJ rate entries (Effective Date | Rate % pa).
- "Last updated: [timestamp]" label.
- **"Check for Updates"** button: calls POST `/api/settings/rates/refresh`, which scrapes `judiciary.hk` and returns a diff. The page shows "3 new rates found" with a preview table.
- **"Apply"** button: calls POST `/api/settings/rates/apply` to write the new entries to `cj_rates.json`. This is a deliberate two-step to prevent accidental overwrite.
- API Key field: shows masked key; "Rotate" button generates a new one.

---

## Technical Requirements

### Back-end (FastAPI, Python 3.11+)

**API Endpoints:**

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/calculate` | Full case payload → per-period results + daily series + explanation |
| `GET` | `/api/rate-presets/cj?date=YYYY-MM-DD` | CJ rate applicable on given date |
| `GET` | `/api/cases` | List saved cases (id, name, updated_at) |
| `POST` | `/api/cases` | Save a new case |
| `GET` | `/api/cases/{id}` | Load a saved case |
| `PUT` | `/api/cases/{id}` | Update an existing case |
| `DELETE` | `/api/cases/{id}` | Delete a case |
| `GET` | `/api/settings/rates` | Return full CJ rate table + last_updated |
| `POST` | `/api/settings/rates/refresh` | Scrape judiciary.hk; return diff (no write) |
| `POST` | `/api/settings/rates/apply` | Write pending diff to cj_rates.json |

FastAPI serves the `frontend/` directory as static files at `/` — no separate web server needed.

**Calculation engine (`calculator.py`) — pure functions, no web dependencies:**

```python
compute_days(start, end, include_start, include_end) -> int
annualise_rate(nominal_rate, rate_basis) -> float
year_fraction(eff_start, eff_end, convention) -> float
effective_period_rate(ann_rate, yf, interest_type, comp_freq) -> float
compute_period(principal_start, initial_principal, interest_basis,
               eff_rate, start_contrib, end_contrib) -> PeriodResult
compute_all_periods(global_settings, periods) -> CaseResult
daily_series(case_result) -> list[DayPoint]
generate_explanation(case_result) -> list[str]
```

**Rate scraper (`rate_scraper.py`):**
- Uses `httpx` to fetch the Judiciary page.
- Parses the two-column HTML table ("Interest Rates on Judgment debts (% per annum)" | "Effective Date") with `BeautifulSoup`.
- Builds a list of `{effective_date: "YYYY-MM-DD", rate: float}` sorted descending.
- Returns only entries not already present in `cj_rates.json` (the diff).
- The scraper is **manually triggered** from the Settings page — never on an automatic schedule — so changes to saved-case data are always deliberate.

**Rate lookup (`rate_presets.py`):**
- `get_cj_rate(date) -> float`: returns the rate with the most recent `effective_date` on or before the query date.
- Raises a descriptive `ValueError` for dates before the earliest entry in the table (currently Q3 2000 based on the Judiciary page).

**Persistence (`case_store.py`):**
- SQLite via SQLAlchemy for MVP (zero-config, file-based).
- Schema: `cases(id UUID PK, name TEXT UNIQUE, payload JSONB, created_at, updated_at)`.
- `payload` stores the full `CaseInput` JSON blob — no schema migration needed when input fields are added.
- Swap to PostgreSQL by changing the connection string when concurrency or scale demands it.

**Authentication (`auth.py`):**
- Single shared API key in `X-API-Key` header; set via environment variable `APP_API_KEY`.
- All `/api/*` routes require the key. Static file routes do not.

**Data models (`models.py`) — Pydantic v2:**
- `GlobalSettings`: `principal: Decimal`, `start_date: date`, `day_count_convention: Literal["Actual/365 Fixed", "Anniversary/365", "Actual/Actual"]`
- `PeriodInput`: all period fields; validator: `end_date > start_date`, `rate >= 0`
- `CaseInput`: `name: str`, `global_settings: GlobalSettings`, `periods: list[PeriodInput]`
- `PeriodResult`: all computed columns (`days`, `year_fraction`, `ann_rate`, `eff_period_rate`, `interest`, `cumulative_interest`, etc.)
- `CaseResult`: `periods: list[PeriodResult]`, `total_interest: Decimal`, `final_amount: Decimal`, `daily_series: list[DayPoint]`, `explanation: list[str]`, `generated_at: datetime`

### Front-end

- Vanilla HTML + JavaScript; no build step.
- **Chart.js** (CDN) for the daily accrual stacked chart.
- **Flatpickr** (CDN) for date pickers.
- All API calls via `fetch()` with `X-API-Key` header (key entered once on load, held in memory — never written to `localStorage`).
- "Copy table" and "Copy all" use the Clipboard API (`navigator.clipboard.writeText`).

---

## Acceptance Criteria

1. *Easy Policy* inputs (principal HK$10,765,000; two periods at 24% pa; matching day-count settings) produce period interests and totals matching the judgment figures to the nearest HKD.
2. All three day-count conventions produce results consistent with the verified spreadsheet.
3. Simple and compound interest (all four compounding frequencies) are mathematically correct per `(1 + r/m)^(m×t) − 1`.
4. The CJ rate button populates the correct rate for any date back to Q3 2000; dates before the earliest entry show an amber warning, not a silent wrong value.
5. A saved case survives a server restart and, when reloaded, produces bit-identical results.
6. The "Check for Updates" flow correctly identifies new rows on the Judiciary page (testable by temporarily prepending a dummy entry to `cj_rates.json`); the "Apply" step writes them correctly.
7. The Explain tab produces well-formed legal prose per period matching the spreadsheet's Explanation sheet style.
8. The Periods tab "Copy table" pastes cleanly into Word and Excel with correct column alignment.
9. The daily chart renders all three stacked series without visual artefacts at period boundaries.
10. The app is fully interactive within 3 seconds on a standard broadband connection; `/api/calculate` responds in under 200ms.

---

## Edge Cases

- **Zero-day period** (adjacent dates, both excluded): Days = 0; Interest = 0. No division-by-zero.
- **Single-day period** (start = end, both included): Days = 1; Year Fraction = 1/365.
- **Leap year** under Actual/Actual: 29 Feb counted correctly.
- **Zero rate**: Interest = 0; principal chain intact.
- **Start date after end date**: Rejected by Pydantic validator before reaching the engine.
- **CJ rate query before earliest entry**: Descriptive `ValueError`; not a silent null.
- **Very large principal** (HK$1B+): Use `Decimal` throughout to avoid floating-point rounding errors visible at HKD precision.
- **20+ periods**: UI table remains scrollable and usable; calculation completes in under 1 second.
- **Scraper failure** (site unreachable or HTML structure changed): Returns a clear error on Settings page; `cj_rates.json` left unchanged.

---

## Performance Considerations

- Engine operates on ≤ 20 periods and ≤ ~10,000 daily data points. Target: `/api/calculate` under 200ms.
- For date ranges exceeding ~15 years, consider returning weekly-sampled points for the chart (reducing JSON payload) while keeping the per-period table exact.
- SQLite is sufficient for a small firm. Migrate to PostgreSQL when concurrent writes or data volume grows.
- Scraper runs are manual and may take 2–5 seconds. A loading spinner on the Settings page is sufficient — no async job queue needed at this scale.

---

## Testing Suggestions

**Unit tests (`test_calculator.py`):**
- `compute_days`: all four include-flag combinations; single-day; zero-day.
- `year_fraction`: all three conventions against known values; leap year; anniversary boundary.
- `effective_period_rate`: simple + all four compounding frequencies; zero rate; large `t`.
- `compute_all_periods`: full *Easy Policy* and *Waddington* verified examples.

**Rate preset tests (`test_rate_presets.py`):**
- Exact effective-date boundary (query date = a rate change date).
- Mid-quarter date (returns most recent prior rate).
- Date before earliest entry → `ValueError`.
- Scraper: parse a saved copy of the Judiciary HTML; assert output matches known-good fixture.

**API tests (`test_api.py`):**
- POST `/api/calculate` with known inputs → response matches expected output to 2 d.p.
- GET `/api/rate-presets/cj` for in-range, boundary, and pre-table dates.
- Case round-trip: POST → GET → assert payload fidelity.
- POST `/api/settings/rates/refresh` against mocked HTTP → assert correct diff returned.

**Regression cases:**
1. *Easy Policy Finance Ltd v 陳海濱* [2025] HKCFI 4295 — two periods, Anniversary/365 + Actual/365 Fixed, simple interest.
2. *Waddington Ltd v Chan Chun Hoo Thomas* (HCA 3291/2003) — single period, Actual/365 Fixed.
3. Compound: 24% pa compounded monthly over 3 years → `(1.02)^36 − 1 ≈ 96.97%`.
4. Zero-rate period between two non-zero periods — principal chain unbroken.

---

## Deferred to Later Phases

- **PDF / Word export** — formatted legal schedule of interest as a downloadable file.
- **Judgment text parsing** — paste a judgment paragraph; AI layer extracts dates, rates, convention hints and pre-fills the form.
- **Per-user accounts** — replace shared API key with OAuth2/JWT; each user has their own case library.
- **Prime rate preset** — structured data source for prime rate history.
- **React front-end migration** — if UI complexity grows to warrant it.

---

*This specification is a living document. Update it as implementation decisions are made.*
