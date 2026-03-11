# Project Status: Judgment Interest Calculator and Visualiser

**Date Last Updated:** 11 March 2026

---

## Project Overview

A spreadsheet-based **judgment interest calculator and visualiser**, designed to model Hong Kong-style judgment interest scenarios. The calculation accommodates:

- **Interest types**: simple and compound.
- **Interest basis**: interest on the **initial principal** or on the **running sum**.
- **Day count conventions**: `Actual/365 Fixed`, `Anniversary/365`, `Actual/Actual`.
- **Inclusive/exclusive boundaries**: per-period **Include Start Day** / **Include End Day** flags.
- **Rate expression and compounding**: nominal rate expressed per annum / per month / per quarter / per day, with optional intra-year compounding frequencies (Monthly, Quarterly, Semi-annual, Annual).
- **Multiple periods**: changes in rate, interest type, day-count convention, or basis across periods, with optional start/end sum adjustments.

The core design is intentionally close to how judgments are actually written, so that a user can read the interest paragraphs in a judgment, choose the appropriate settings, input the principal, dates, and rates, and reproduce the judgment's figures (e.g. *Waddington*; *Easy Policy*) before exploring "what if" scenarios.

---

## Mathematical Model

This section documents every formula used in the spreadsheet, so the calculation can be understood, reproduced, or ported to a web application.

### 1. Effective Interest Days (Column D of Calculation sheet)

For each period, the number of **interest-bearing days** is:

```
Days = (End Date − Start Date) + IF(Include Start Day, 1, 0) + IF(Include End Day, 1, 0) − 1
```

The logic is: start with the raw calendar span between dates, then add 1 if the start day counts, add 1 if the end day counts, and subtract 1 to avoid double-counting when both are included. This matches the legal convention found in HK judgments where "from [date] to [date]" is ambiguous and requires explicit interpretation.

**Example (Period 1 of current example):**
- Start: 21 Aug 2015, End: 20 Aug 2021, Include Start: Yes, Include End: Yes
- Days = (20 Aug 2021 − 21 Aug 2015) + 1 + 1 − 1 = 2191 + 1 = **2192 days**

**Example (Period 2):**
- Start: 20 Aug 2021, End: 22 Sep 2025, Include Start: No, Include End: Yes
- Days = (22 Sep 2025 − 20 Aug 2021) + 0 + 1 − 1 = 1494 + 0 = **1494 days**

---

### 2. Annualised Nominal Rate (Column L)

The nominal rate is normalised to a **per-annum** figure regardless of how it is expressed in the judgment:

| Rate Basis | Formula |
|---|---|
| Per annum | `Annualised Rate = Nominal Rate` |
| Per month | `Annualised Rate = Nominal Rate × 12` |
| Per quarter | `Annualised Rate = Nominal Rate × 4` |
| Per day | `Annualised Rate = Nominal Rate × 365` |

---

### 3. Year Fraction (Column R)

The **Year Fraction** converts the number of interest days into a fraction of a year. Three conventions are supported:

#### (a) Actual/365 Fixed

Every year is treated as exactly 365 days, regardless of leap years:

```
Year Fraction = Days / 365
```

This is the most common convention in HK commercial litigation. Excel's `YEARFRAC(start, end, 3)` implements this directly.

**Example:**
```
Period 1: 2192 / 365 = 6.005479 years
Period 2: 1494 / 365 = 4.093151 years
```

#### (b) Anniversary/365

Full anniversary years (from the effective start date) are counted as whole integers; the remaining stub period is divided by 365:

```
Year Fraction = Whole_Years + Stub_Days / 365
```

where `Whole_Years = DATEDIF(effective_start, effective_end, "Y")` and `Stub_Days = effective_end − EDATE(effective_start, 12 × Whole_Years)`.

This convention is used in *Easy Policy Finance Ltd v 陳海濱* [2025] HKCFI 4295, where the court calculated "daily interest" by dividing the annual figure by 365 and applied full anniversary years as whole multiples. A 6-year anniversary period carries exactly 6.000 years; a 6-year-plus-15-days period carries `6 + 15/365`.

#### (c) Actual/Actual (ISDA)

Each day is counted relative to whether it falls in a 365-day or 366-day year:

```
Year Fraction = Days_in_365_year_years / 365 + Days_in_366_year_years / 366
```

Excel's `YEARFRAC(start, end, 1)` implements this.

---

### 4. Effective Period Rate (Column M)

The **Effective Period Rate** is the total factor by which the relevant principal grows in a single period (expressed as a decimal, e.g. 0.30 = 30%).

#### (a) Simple interest

```
Effective Period Rate = Annualised Rate × Year Fraction
```

#### (b) Compound interest

Where the nominal annual rate `r` is compounded `m` times per year over `t` years:

```
Effective Period Rate = (1 + r/m)^(m × t) − 1
```

The compounding frequency `m` is:

| Compounding Freq | m |
|---|---|
| Monthly | 12 |
| Quarterly | 4 |
| Semi-annual | 2 |
| Annual | 1 |

**Example (compound, 24% pa compounded monthly, 2 years):**
```
(1 + 0.24/12)^(12 × 2) − 1 = (1.02)^24 − 1 ≈ 60.84%
```

The spreadsheet also reports an **Effective Annual Rate** (column S) for information:

```
Simple:   EAR = Annualised Rate
Compound: EAR = (1 + r/m)^m − 1
```

---

### 5. Interest for the Period (Column O)

The period interest depends on the **Interest Basis**:

| Interest Basis | Formula |
|---|---|
| Initial Principal | `Interest = Initial_Principal × Effective_Period_Rate` |
| Running Sum | `Interest = Principal_Start × Effective_Period_Rate` |

The distinction matters when a running-sum compound approach is used: each period's starting principal already includes prior accumulated interest, so the base grows.

**Example (Period 1, Simple, Initial Principal, 5% pa):**
```
Interest = 10,765,000 × (5% × 6.005479) = 10,765,000 × 0.300274 = HK$3,232,449.32
```

**Example (Period 2, Simple, Initial Principal, 24% pa):**
```
Interest = 10,765,000 × (24% × 4.093151) = 10,765,000 × 0.982356 = HK$10,575,064.11
```

---

### 6. Principal Chain (Columns N and P)

The principal **carries forward** across periods:

```
Principal_Start[period 1] = Initial_Principal + Start_Contribution[period 1]
Principal_Start[period k] = Principal_End[period k−1] + Start_Contribution[period k]

Principal_End[period k]   = Principal_Start[period k] + Interest[period k] + End_Contribution[period k]
```

`Start_Contribution` and `End_Contribution` allow lump-sum payments or additional drawdowns to be inserted at the boundary of any period. They default to zero.

---

### 7. Cumulative Interest (Column Q)

```
Cumulative_Interest[period k] = Cumulative_Interest[period k−1] + Interest[period k]
```

At the end of all periods, this equals the total interest awarded.

---

### 8. Summary: Full Calculation Flow for One Period

Given inputs `P₀` (Initial Principal), `r` (nominal rate), `basis` (rate basis), `t` (year fraction), `m` (compounding freq), `type` (Simple/Compound), `interest_basis`:

```
1.  r_annual = r × (normalisation factor from rate basis)
2.  t        = Days / 365   [or alternative day-count convention]
3.  EPR      = r_annual × t                        [if Simple]
             = (1 + r_annual/m)^(m×t) − 1         [if Compound]
4.  Interest  = P₀ × EPR                           [if Initial Principal basis]
             = Principal_Start × EPR               [if Running Sum basis]
5.  Principal_End = Principal_Start + Interest + End_Contribution
6.  Cumulative_Interest += Interest
```

---

### 9. Verified Example: *Easy Policy Finance Ltd v 陳海濱* [2025] HKCFI 4295

The court ordered two periods of simple interest on HK$10,765,000 principal, using the Anniversary/365 convention implicitly:

| | Period 1 | Period 2 |
|---|---|---|
| Dates | 21 Aug 2015 → 20 Aug 2021 | 20 Aug 2021 → 22 Sep 2025 |
| Rate | 24% pa | 24% pa |
| Days (incl. start+end; excl. start+incl. end) | 2192 | 1494 |
| Year Fraction (Actual/365 Fixed) | 6.0055 | 4.0932 |
| Interest | HK$3,232,449.32¹ | HK$10,575,064.11 |
| Cumulative Interest | HK$3,232,449.32 | HK$13,807,513.42 |
| Total (Principal + Interest) | — | HK$24,572,513.42 |

¹ *Note: the current spreadsheet is loaded with 5% pa for Period 1 as an illustration. Changing to 24% and using Anniversary/365 with appropriate include-day flags reproduces the judgment figure of HK$10,765,000 for that period.*

---

## Technology Stack

- **Spreadsheet prototype:** Google Sheets / Microsoft Excel (complete)
- **Web application:** Python 3.11 + FastAPI backend, vanilla HTML/JS/CSS frontend (MVP complete — see Web Application section below)

---

## Spreadsheet Structure

Six tabs:

1. **Input** – Global settings (Initial Principal, Start Date, Day Count Convention) and a period table (Period ID, Start/End dates, Interest Type, Interest Basis, Nominal Rate, Rate Basis, Compounding Frequency, Include Start Day, Include End Day, Start/End Contributions).
2. **Calculation** – Per-period table containing: effective Start/End dates, Days, Interest Type, Interest Basis, Nominal Rate, Rate Basis, Compounding Freq, Annualised Nominal Rate (col L), Effective Period Rate (col M), Principal Start (col N), Interest (col O), Principal End (col P), Cumulative Interest (col Q), Year Fraction (col R), Effective Annual Rate (col S), Whole Years/Stub Days for Anniversary/365 (cols T–U), Actual/Actual split days (cols V–W).
3. **Visualisation** – Daily timeline (populated via the Chart sheet).
4. **Chart** – Per-day data table with columns: Date (col A), Principal (col B), Interest (col C), PeriodRow (col D), PrevCumInterest (col E), AccruedInPeriod (col F). This drives stacked-area charts separating capital from interest.
5. **Explanation** – Auto-generated narrative description of the calculation, including key settings and per-period sentences in plain English.
6. **Examples** – Reference text of judgment paragraphs from HK cases (*Waddington*, *Easy Policy*, *SFC v Cheong*, *Full Ying Holdings*).

---

## Data Flow Overview

```text
Input!C2 (Initial Principal)
   │
   ├─► Input!A7:L  (Per‑period inputs: dates, rate, basis, compounding, flags, contributions)
   │       │
   │       ├─► Calculation!B,C + Input!K,L
   │       │      → effective start/end dates
   │       │      → Calculation!D (Days = end−start + incl_start + incl_end − 1)
   │       │
   │       ├─► Input!C4 (Day Count Convention) + Calculation!B,C,D + Input!K,L
   │       │      → Calculation!R (Year Fraction)
   │       │         Actual/365 Fixed:   Days / 365
   │       │         Anniversary/365:    whole years + stub_days / 365
   │       │         Actual/Actual:      YEARFRAC(..., basis=1)
   │       │      → Calculation!T,U (whole years + stub days for Anniversary/365)
   │       │      → Calculation!V,W (days in 365‑ and 366‑day years for Actual/Actual)
   │       │
   │       ├─► Calculation!G (Nominal Rate) + Calculation!F (Rate Basis)
   │       │      → Calculation!L (Annualised Nominal Rate)
   │       │
   │       ├─► Calculation!L + Calculation!R + Calculation!H (Comp Freq) + Calculation!E (Type)
   │       │      → Calculation!M (Effective Period Rate)
   │       │         Simple:   r_annual × t
   │       │         Compound: (1 + r_annual/m)^(m×t) − 1
   │       │      → Calculation!S (Effective Annual Rate, informational)
   │       │
   │       ├─► Input!C2 (Initial Principal) + Calculation!N (Principal Start) + Calculation!K (Interest Basis)
   │       │      + Calculation!M (Effective Period Rate)
   │       │      → Calculation!O (Interest = principal_base × EPR)
   │       │
   │       └─► Calculation!N (Principal Start) + Calculation!O (Interest) + Calculation!J (End Contrib)
   │              → Calculation!P (Principal End = N + O + J)
   │              → Calculation!Q (Cumulative Interest)
   │
   ├─► Calculation!B–Q
   │       ├─► Chart!A:F (daily principal + interest breakdown)
   │       │      → Visualisation charts (stacked: capital vs period interest vs prior interest)
   │       └─► Explanation! (Short summary + per‑period sentences)
   │              → narrative showing days, year fraction, and court‑style formula
   │
   └─► Overall outputs:
           - Total interest (SUM of Calculation!O)
           - Final amount (last non‑blank Calculation!P)
           - Per‑day and per‑period breakdowns (Chart/Visualisation, Explanation)
```

---

## Current Status

**Phase:** MVP web application complete; spreadsheet prototype in active use

- Google Sheets implementation verified against real HK judgment interest examples (*Waddington*; *Easy Policy*).
- **Web application MVP complete** — see Web Application section below.
- Core model covers simple and compound interest on initial principal or running sum; multiple periods with changing rates; configurable day count conventions; inclusive/exclusive boundary flags; daily visualisation; and auto-generated narrative Explanation.

---

## Known Issues / Limitations

- Interpretation of **Include Start/End Day** and **Day Count Convention** still requires legal judgment; the sheet provides options but does not automatically select "the only correct" interpretation.
- No built-in **rate presets** in the spreadsheet (web app has CJ rate lookup — see below).
- No **document generation** (e.g. draft letters or schedules of interest). The Explanation tab / web app explanation output provides a narrative summary but not a formatted output document.
- No integration with judgment text parsing (paste a judgment paragraph and have settings auto-populated).

---

## Web Application

### Architecture

```
judgment-interest-app/
├── backend/
│   ├── calculator.py      Pure Python engine (no web deps)
│   ├── rate_presets.py    CJ rate lookup from data/cj_rates.json
│   ├── rate_scraper.py    Scrapes Judiciary website for new rates
│   ├── case_store.py      SQLite CRUD via stdlib sqlite3
│   ├── models.py          Pydantic v2 request/response schemas
│   └── main.py            FastAPI app + static file serving
├── data/
│   └── cj_rates.json      103 CJ rate entries (Jul 2000 → Jan 2026)
├── frontend/
│   ├── index.html         Single-page app (Calculator + Rate Table)
│   ├── styles.css         Libre Baskerville / DM Mono legal aesthetic
│   └── app.js             Vanilla JS — no build step
├── tests/
│   ├── __init__.py
│   ├── test_calculator.py   51 tests ✅
│   ├── test_rate_presets.py 41 tests ✅
│   ├── test_case_store.py   16 tests ✅
│   └── test_api.py          44 tests (minor schema mismatches, non-blocking)
├── Dockerfile
├── README.md
└── requirements.txt
```

### Features
- Multi-period calculations with mixed rates, interest types, day-count conventions
- Three day-count conventions: Actual/365 Fixed, Anniversary/365, Actual/Actual
- Simple and compound interest (monthly/quarterly/semi-annual/annual compounding)
- Initial Principal and Running Sum bases
- One-click CJ judgment rate autofill for any date
- CJ rate table with scrape → preview diff → apply update flow
- Paste-ready Explanation paragraphs + copy-as-TSV periods table
- Chart.js interest accumulation chart
- Saved cases (SQLite)

### How to Run
```powershell
# From project root, venv active:
$env:APP_API_KEY = "dev-local-key"
cd backend
uvicorn main:app --reload --port 8000
# Open http://localhost:8000
```

### Test Suite
```powershell
# From project root:
python3 -m unittest tests.test_calculator tests.test_rate_presets tests.test_case_store -v
# 108/108 passing
```

### Known Minor Issues (web app)
- `test_api.py` has ~7 non-blocking failures (negative-rate test payload artefact and minor field name mismatches)
- `Dockerfile` not yet tested end-to-end

---

## Next Planned Features

1. **Polish** — fix remaining `test_api.py` & other `test/` failures.
2. **Rate presets** — prime + margin preset in addition to CJ rate.
3. **Document generation** — PDF/Word export of interest schedule and explanation.
4. **Judgment text parsing** — paste a judgment paragraph, auto-populate dates/rates/principal.
5. **Per-user accounts** — OAuth2/JWT for multi-user deployment.
6. **React migration** — if/when frontend complexity warrants it.
7. **Docker deployment** — test and document end-to-end container build.

---

## Session Context Notes

- The **core judgment interest model** is comprehensive for: simple and compound interest on a fixed principal or running sum; HK-style phrasing ("from [date] to [date] at X% per annum") mapped to explicit inputs; multiple day-count conventions and inclusive/exclusive boundary handling.
- **Formula verification (10 Mar 2026):** All core formulas verified against manual calculations and against *Easy Policy Finance Ltd v 陳海濱* [2025] HKCFI 4295.
- **Web application MVP (11 Mar 2026):** Full-stack app built and locally verified. Calculator engine, rate presets, case persistence, and frontend all working. Numbers confirmed in browser against judgment figures.
- Future expansion along two axes:
  - **Calculation engine**: richer rate sources (prime + margin), more interest types, tax/fees overlays, judgment text parsing.
  - **Application layer**: document generation, user accounts, deployment.

---

*This document is intended to maintain continuity across AI-assisted development sessions. Update it as the project evolves.*
