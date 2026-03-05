```markdown
# New Feature: Initial Spreadsheet Setup (Approach 1)

## Technical Design Decision

- **Chosen approach**: **Approach 1 – Pure spreadsheet formulas and native features (no scripting/macros)**.
- **Brief description**: The interest calculator is implemented entirely within a spreadsheet (Google Sheets or Excel) using three sheets (`Input`, `Calculation`, `Chart`). Users add rows directly to the `Input` table to describe periods where parameters change; the `Calculation` sheet uses formulas to compute per-period durations, interest amounts, and accumulated sums; the `Chart` sheet visualises the accumulated sum over time.
- **Why this approach was selected over alternatives**:
  - Keeps the **initial version lightweight and transparent**, with all logic visible as formulas rather than hidden in scripts or an external codebase.
  - Avoids the **complexity and platform divergence** of maintaining Apps Script / VBA / Office Scripts logic (Approach 2) while still achieving a functional calculator.
  - A separate web application (Approach 3) would be **overkill for the current phase**, requiring additional infrastructure and moving away from the "spreadsheet-first" goal.
  - Supports **rapid iteration** on formulas and layout while the exact requirements for interest rules and visualisation are still being refined.
- **Constraints and assumptions**:
  - The `Input` sheet will use a **structured table with manual row insertion** instead of a programmatic "`+` button"; formulas will be designed to auto-fill down the table.
  - The first version focuses on **per-period calculations** (each row is a period) rather than generating a row for every internal compounding event. The chart x‑axis will therefore be at **period granularity**, not strictly at the smallest compounding frequency across all periods.
  - The initial implementation targets **modern versions of Google Sheets and/or Excel 365**, assuming availability of common functions such as `IF`, `INDEX`, `MATCH`/`XLOOKUP`, and basic date functions. Any platform-specific refinements can be added later if needed.
```

