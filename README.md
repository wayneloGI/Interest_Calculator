# HK Judgment Interest Calculator

A professional-grade tool for computing post-judgment interest under Hong Kong law, porting and extending the [PROJ-DEV-LAWS spreadsheet](../PROJ-DEV-LAWS_Judgment_Interest_Calculator.xlsx).

## Features

- Multi-period calculations with mixed rates, interest types and day-count conventions
- Three day-count conventions: Actual/365 Fixed, Anniversary/365, Actual/Actual
- Simple and compound interest (monthly, quarterly, semi-annual, annual compounding)
- Initial Principal and Running Sum interest bases
- One-click CJ judgment rate lookup for any date
- CJ rate table with scrape-and-preview update flow
- Exportable explanation paragraphs and TSV period table
- Saved cases (SQLite)

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your API key
export APP_API_KEY=your-secret-key

# 3. Initialise the database
python -c "import sys; sys.path.insert(0,'backend'); from case_store import init_db; init_db()"

# 4. Start the server
cd backend
uvicorn main:app --reload --port 8000
```

The app is now at **http://localhost:8000**.  
API docs are at **http://localhost:8000/api/docs**.

## Docker

```bash
docker build -t judgment-interest .
docker run -e APP_API_KEY=your-secret -p 8000:8000 judgment-interest
```

## Project structure

```
backend/
  calculator.py      Pure-Python interest engine (no web deps)
  rate_presets.py    CJ rate lookup from data/cj_rates.json
  rate_scraper.py    Scrapes the Judiciary website for new rates
  case_store.py      SQLite CRUD for saved cases (stdlib sqlite3)
  models.py          Pydantic v2 request/response schemas
  main.py            FastAPI app — routes + static file serving
data/
  cj_rates.json      103 CJ rate entries (Jul 2000 → Jan 2026)
  cases.db           SQLite database (created on first run)
frontend/
  index.html         Single-page application
  styles.css         Libre Baskerville / DM Mono legal aesthetic
  app.js             Vanilla JS — no build step required
tests/
  test_calculator.py   51 tests — pure engine
  test_rate_presets.py 41 tests — rate lookup + scraper parsing
  test_case_store.py   16 tests — SQLite CRUD
  test_api.py          37 tests — FastAPI routes (requires FastAPI)
```

## Running tests

```bash
# All tests (excluding test_api.py which needs FastAPI):
python -m unittest tests.test_calculator tests.test_rate_presets tests.test_case_store -v

# Full suite (including API tests — needs: pip install fastapi httpx pydantic):
python -m unittest discover -s tests -v
```

## Configuration

| Environment variable | Description | Default |
|---|---|---|
| `APP_API_KEY` | Required. Shared secret for the `X-API-Key` header. | — |
| `PORT` | Server port | `8000` |
| `RELOAD` | `true` enables uvicorn hot-reload | `false` |

## Setting the API key in the browser

The frontend reads `window.__API_KEY__`.  In development, you can inject it by adding a `<script>` tag before `app.js`:

```html
<script>window.__API_KEY__ = "your-secret-key";</script>
```

In production, the recommended approach is to have the FastAPI server render a minimal HTML template that injects the key, rather than hardcoding it in a static file.

## Verified against

- **Easy Policy Finance Ltd v 陳海濱 [2025] HKCFI 4295**  
  Period 1: HK$3,232,449.32 ✓  
  Period 2: HK$10,575,064.11 ✓  
  Total interest: HK$13,807,513.43 ✓

## Deferred to later phases

- PDF / Word export of calculation reports
- Judgment text parsing (extract figures from a judgment PDF)
- Per-user accounts (OAuth2 / JWT)
- React migration
- Prime rate preset
