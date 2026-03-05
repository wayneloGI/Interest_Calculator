# Judgment Interest Calculator (Spreadsheet)

This repository contains documentation and supporting files for a spreadsheet‑based **judgment interest calculator and visualiser**, designed around Hong Kong–style interest paragraphs (e.g. Waddington; Easy Policy).

The core calculation currently lives in a **Google Sheets workbook** (or equivalent Excel file), which models:
- Simple and compound interest on either the **initial principal** or the **running sum**.
- Multiple periods with changing rates, interest types, and legal boundaries.
- Configurable **day count conventions** (`Actual/365 Fixed`, `Anniversary/365`, `Actual/Actual`).
- Per‑period **Include Start Day / Include End Day** flags to match the wording of specific judgments.
- A daily **visualisation** sheet and an **explanation** sheet that turns each period into a narrative formula (principal × rate × years).

## How to use this project

1. Open the main spreadsheet (Google Sheets link or `.xlsx` file) once it is added to the `spreadsheet/` folder.
2. On the **Input** sheet:
   - Enter the **Initial Principal**, **Start Date**, and choose a **Day Count Convention**.
   - For each period, fill in the end date, nominal rate, rate basis, interest type, interest basis, and include‑day flags.
3. Review the **Calculation** and **Visualisation** sheets to see how interest days, year fractions, and interest amounts are derived.
4. Use the **Explanation** sheet as a starting point for written explanations to clients or counterparties.

For a more detailed description of the model, see `project_status.md`.

