```markdown
# Project Status: Judgment Interest Calculator and Visualiser

**Date Last Updated:** 3 March 2026 (evening)

## Project Overview
A spreadsheet-based **judgment interest calculator and visualiser**, designed to model Hong Kong-style judgment interest scenarios. The calculation currently accommodates:
- **Interest types**: simple and compound.
- **Interest basis**: interest on the **initial principal** or on the **running sum**.
- **Day count conventions**: `Actual/365 Fixed`, `Anniversary/365`, `Actual/Actual`.
- **Inclusive/exclusive boundaries**: per-period **Include Start Day** / **Include End Day** flags.
- **Rate expression and compounding**: nominal rate expressed per annum / per month / per quarter / per day, with optional intra-year compounding frequencies.
- **Multiple periods**: changes in rate, interest type, day-count convention, or basis across periods, with no contributions by default and optional start/end adjustments.

The core design is intentionally close to how judgments are actually written, so that a user can:
- Read the interest paragraphs in a judgment.
- Choose the appropriate **Day Count Convention** and **include-day flags**.
- Input the principal, dates, and rates.
- Reproduce the judgment’s figures (e.g. Waddington; Easy Policy) and then explore “what if” scenarios.

The spreadsheet consists of 3 logical sheets (tabs may be named differently in specific files):
1. **Input Sheet** – Global settings (Initial Principal, Start Date, Day Count Convention) and a periods table (Period ID, Start/End dates, Interest Type, Interest Basis, Nominal Rate, Rate Basis, Compounding Frequency, Include Start/End Day, Start/End Contributions).
2. **Calculation Sheet** – A per-period table containing:
   - Calendar start/end dates and effective **Days** (after include-day flags).
   - **Annualised Nominal Rate**, **Year Fraction**, **Effective Period Rate**.
   - **Principal Start**, **Interest**, **Principal End**, **Cumulative Interest**.
3. **Visualisation Sheet** – Daily timeline derived from the Calculation sheet, with one or more charts:
   - Stacked views separating **principal**, **previous cumulative interest**, and **interest accrued in the current period**.
   - Option to display simple-interest periods as linear growth and compound-interest periods as exponential growth, on a per-day x-axis.

## Technology Stack
- **Primary:** Spreadsheet application (Google Sheets / Microsoft Excel)
- **Recommendations for future expansion:**
  - If more complex workflows, document automation, or user management are needed, consider a lightweight web application (e.g., Python with FastAPI/Flask or JavaScript with Next.js/React) backed by a database.
  - For now, the spreadsheet implementation is the **core calculation engine** and reference implementation; a future app would likely call into the same logic.

## Project Structure
*Current / expected structure:*
```
/
├── README.md
├── project_status.md
├── new_feature.md
└── spreadsheet/
    ├── Judgment_Interest_Calculator.xlsx (or Google Sheets link)
    └── [Any supporting scripts if using macros/AppScript]
```

## Current Status
**Phase:** Working spreadsheet prototype (Approach 1)  
- Google Sheets implementation in active use for real HK judgment interest examples (e.g. Waddington; Easy Policy).  
- Core model covers:
  - Simple and compound interest on initial principal or running sum.
  - Multiple periods with changing rates and legal boundaries.
  - Configurable day count conventions and inclusive/exclusive flags.
  - Daily visualisation separating capital and different interest components.
  - An `Explanation` sheet that turns each period into a narrative sentence, explicitly showing how: interest days are counted (including/excluding start/end days), the chosen day count convention converts days into a year fraction, and the court-style formula (principal × rate × years) yields the interest.

## Data Flow Overview

The main calculation flow can be summarised as:

```text
Input!C2 (Initial Principal)
   │
   ├─► Input!A7:L  (Per‑period inputs: dates, rate, basis, compounding, flags, contributions)
   │       │
   │       ├─► Calculation!B,C + Input!K,L
   │       │      → effective start/end dates
   │       │      → Calculation!D (Days)
   │       │
   │       ├─► Input!C4 (Day Count Convention) + Calculation!B,C,D + Input!K,L
   │       │      → Calculation!R (Year Fraction)
   │       │      → Calculation!T,U (whole years + stub days for Anniversary/365)
   │       │      → Calculation!V,W (days in 365‑ and 366‑day years for Actual/Actual)
   │       │
   │       ├─► Calculation!G (Nominal Rate) + Calculation!F (Rate Basis)
   │       │      → Calculation!L (Annualised Nominal Rate)
   │       │
   │       ├─► Calculation!L + Calculation!R + Calculation!H (Comp Freq) + Calculation!E (Type)
   │       │      → Calculation!M (Effective Period Rate)
   │       │      → Calculation!S (Effective Annual Rate, informational)
   │       │
   │       ├─► Input!C2 (Initial Principal) + Calculation!N (Principal Start) + Calculation!K (Interest Basis)
   │       │      + Calculation!M (Effective Period Rate)
   │       │      → Calculation!O (Interest for the period)
   │       │
   │       └─► Calculation!N (Principal Start) + Calculation!O (Interest) + Calculation!J (End Contrib)
   │              → Calculation!P (Principal End)
   │              → Calculation!Q (Cumulative Interest)
   │
   ├─► Calculation!B–Q
   │       ├─► Visualisation!A:C (daily principal + interest breakdown)
   │       │      → charts showing capital vs interest over time
   │       └─► Explanation! (Short summary + per‑period sentences)
   │              → narrative explanation of each period and how
   │                the year fraction and interest are derived
   │
   └─► Overall outputs:
           - Total interest (sum of Calculation!O)
           - Final amount (max of Calculation!P)
           - Per‑day and per‑period breakdowns (Visualisation, Explanation)
```

## Known Issues / Limitations
- Interpretation of **Include Start/End Day** and **Day Count Convention** still requires legal judgment; the sheet provides options but does not choose “the only correct” interpretation automatically.
- No built-in notion of **“usual rates”** (e.g. Chief Justice’s rates), prime + margin, or jurisdiction-specific default rules; these must be entered manually as nominal rates.
- No automation for **document generation** (e.g. draft letters or submissions explaining the calculations).
- No integration yet with external data sources (e.g. rate tables, judgment text).

## Next Planned Feature
- Add a `Tests` sheet with curated examples (simple, compound, different day count conventions, rate changes) to regression-test the model.
- Add optional lookups for **rate presets**, e.g.:
  - Chief Justice’s published judgment interest rates by date.
  - Bank prime rate + fixed margin (prime + n%).
- Explore a thin web or desktop front-end that:
  - Accepts high-level inputs (dates, principal, rate type, convention).
  - Calls the spreadsheet logic (or a ported engine) to compute results.
  - Generates solicitor-facing deliverables (e.g. summary tables, narrative explanation, counter-party letters) as templated outputs.

## Session Context Notes
*Use this section to record decisions, assumptions, or important context from the current session.*
- The **core judgment interest model** is now reasonably comprehensive for:
  - Simple and compound interest on a fixed principal or running sum.
  - Hong Kong-style phrasing (“from [date] to [date] at X% per annum”), with explicit examples showing how to map wording to inputs.
  - Multiple day-count conventions and inclusive/exclusive boundary handling.
- Future expansion is expected along two axes:
  - **Calculation engine**: richer rate sources (CJ rates, prime + margin), more interest types, tax/fees overlays.
  - **Application layer**: upload or paste judgment extracts, parse interest paragraphs, suggest input settings, and produce human-readable explanations and schedules.

---
*This document is intended to maintain continuity across AI-assisted development sessions. Update it as the project evolves.*
```