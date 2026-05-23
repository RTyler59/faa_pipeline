# FAA Air Operator Data Pipeline

An automated ETL pipeline that harvests FAA Air Operator certification data for all five active 14 CFR parts (121, 125, 129, 133, 135) from the official FAA Tableau dashboard and loads it into a PostgreSQL database for downstream analysis.

---

## Overview

The FAA publishes Air Operator certificate data through an interactive Tableau dashboard that requires JavaScript execution and UI interaction to expose its data — it is not accessible via static HTTP requests. This pipeline automates the full data collection cycle:

1. **Harvest** — A Playwright-driven browser navigates the Tableau dashboard, scrolls through each FAR part's operator list, and captures each viewport using Tesseract OCR.
2. **Parse** — A regex-based text parser processes the raw OCR output and extracts structured operator records into a CSV file.
3. **Ingest** — A PostgreSQL loader reads the CSV and upserts all records into the database, tracking inserts vs. updates.

---

## Tech Stack

| Component | Technology | Purpose |
|---|---|---|
| Browser automation | [Playwright](https://playwright.dev/python/) (sync API) | Render the JS dashboard, handle toggles, scroll |
| OCR | [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) + [pytesseract](https://github.com/madmaze/pytesseract) | Extract text from viewport screenshots |
| Image processing | [Pillow](https://python-pillow.org/) | Crop column strips, upscale for OCR accuracy |
| Database driver | [psycopg2-binary](https://pypi.org/project/psycopg2-binary/) | PostgreSQL connectivity, parameterized UPSERT |
| Database | PostgreSQL 14+ | Persistent operator store |
| Config | [python-dotenv](https://pypi.org/project/python-dotenv/) | `.env`-based settings |
| Testing | [pytest](https://pytest.org/) + [pytest-mock](https://pypi.org/project/pytest-mock/) | Unit and integration tests |

---

## Data Source

**URL:** [https://explore.dot.gov/t/FAA/views/AVInfo_AirOperators/AirOperators](https://explore.dot.gov/t/FAA/views/AVInfo_AirOperators/AirOperators)

The dashboard presents operators grouped by FAR part in a three-column Tableau grid. Each operator record includes:

- Certificate number, issue date, and designator code
- Operator legal name and any d/b/a aliases
- CEO name and mailing address
- Director of Operations, Director of Maintenance, Chief Pilot
- Employee counts: PIC Captains, Inspectors, Designated Inspectors, Certificated Mechanics, Noncertificated Mechanics, Total Employees

---

## Database Schema

Three tables with idempotent `CREATE TABLE IF NOT EXISTS` — safe to re-apply:

```
air_operators          — primary record, keyed on certificate_number
operator_dba_names     — 0-to-N aliases per operator (independently queryable)
aircraft               — 0-to-N aircraft per operator (make/model/series)
```

Key design decisions:
- `UPSERT` on `certificate_number` (FAA's natural unique key) keeps re-runs idempotent.
- All personnel/count columns are nullable — they vary by CFR part (e.g. `inspectors` and `designated_inspectors` appear only on Part 121/129 records).
- A GIN full-text index on `operator_name` supports fast marketing lookups.
- DBA names are stored as child rows rather than an array so each alias is independently queryable.

---

## Prerequisites

### 1. Python 3.10+

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Tesseract OCR Engine

Download and install from: https://github.com/UB-Mannheim/tesseract/wiki

Default install path (Windows):
```
C:\Users\<you>\AppData\Local\Programs\Tesseract-OCR\tesseract.exe
```

If installed elsewhere, update `TESSERACT_CMD` at the top of `scraper/harvest.py`.

### 3. PostgreSQL

Create a database and user:

```sql
CREATE DATABASE faa_operators;
CREATE USER faa_user WITH PASSWORD 'changeme';
GRANT ALL PRIVILEGES ON DATABASE faa_operators TO faa_user;
```

Apply the schema:

```bash
psql -U faa_user -d faa_operators -f db/schema.sql
```

### 4. Environment variables

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

```ini
DB_HOST=localhost
DB_PORT=5432
DB_NAME=faa_operators
DB_USER=faa_user
DB_PASS=changeme
```

---

## Running the Pipeline

The pipeline is three sequential steps:

### Step 1 — Harvest

Navigates the FAA dashboard, scrolls all five FAR parts, and OCRs the operator data into a raw text dump.

```bash
python -m scraper.harvest
```

**Options:**
```bash
python -m scraper.harvest --headed   # Run with a visible browser window (useful for calibration)
```

Output: `data/faa_raw_dump.txt`

> **Runtime:** ~30–60 minutes depending on operator count and scroll depth. The dashboard is scrolled column-by-column for each FAR part with settle delays between viewport captures to ensure accurate OCR.

### Step 2 — Parse

Processes the raw OCR dump into a structured CSV.

```bash
python -m scraper.text_parser
```

**Options:**
```bash
python -m scraper.text_parser --in data/faa_raw_dump.txt --out data/operators.csv
```

Output: `data/operators.csv`

### Step 3 — Ingest

Loads the CSV into PostgreSQL using an idempotent UPSERT. Re-running is safe — existing records are updated, not duplicated.

```bash
python -m db.ingest
```

**Options:**
```bash
python -m db.ingest --dry-run          # Preview first 10 rows without writing to DB
python -m db.ingest --csv path/to.csv  # Use a different CSV file
```

---

## Verifying the Data

Connect to your PostgreSQL database and run:

```sql
-- Record counts by FAR part
SELECT cfr_part, COUNT(*) AS operators
FROM air_operators
GROUP BY cfr_part
ORDER BY cfr_part;

-- Operators with the most employees
SELECT operator_name, cfr_part, total_employees
FROM air_operators
WHERE total_employees IS NOT NULL
ORDER BY total_employees DESC
LIMIT 20;

-- Full-text search on operator name
SELECT operator_name, certificate_number, cfr_part
FROM air_operators
WHERE to_tsvector('english', operator_name) @@ plainto_tsquery('english', 'delta');

-- All known DBA aliases for a given operator
SELECT ao.operator_name, d.dba_name
FROM air_operators ao
JOIN operator_dba_names d ON d.operator_id = ao.id
WHERE ao.certificate_number = 'DALA026A';
```

---

## Project Structure

```
FAA_Pipeline/
├── .env.example              # Config template — copy to .env and fill in credentials
├── requirements.txt          # Python dependencies
├── PRD.md                    # Product requirements document
├── sample_data.md            # Manual reference sample showing target OCR output format
│
├── config/
│   └── settings.py           # Loads .env into a frozen Settings dataclass
│
├── db/
│   ├── schema.sql            # Idempotent CREATE TABLE / INDEX statements
│   ├── ingest.py             # CSV → PostgreSQL UPSERT loader
│   ├── repository.py         # Parameterized SQL helpers
│   └── connection.py         # psycopg2 connection pool
│
├── scraper/
│   ├── harvest.py            # Playwright scroll-and-OCR harvester
│   └── text_parser.py        # Raw OCR text → structured CSV
│
├── utils/
│   ├── logger.py             # JSON-structured logging setup
│   └── retry.py              # tenacity retry decorator factory
│
└── tests/                    # pytest test suite
    └── fixtures/             # HTML/text fixtures for unit tests
```

---

## Coordinate Calibration

The harvester uses fixed pixel coordinates tuned for a **1280 × 800** browser viewport against the current FAA dashboard layout. If the dashboard is redesigned or the viewport changes, the following constants in `scraper/harvest.py` will need recalibration:

| Constant | Description |
|---|---|
| `SHOW_AIRCRAFT_XY` | Click target for the "Show Aircraft" toggle |
| `FAR_PART_COORDS` | Click targets for each FAR part bar in the chart |
| `DATA_PANEL_CROP` | PIL crop box defining the visible data panel area |
| `COLUMN_DIVIDERS` | x-offsets of the white gaps between Tableau's 3 columns |
| `SCROLL_XY` | Mouse position used for wheel scroll events |
| `SCROLL_STEP` | Pixels per scroll event |

**To recalibrate:** run `python -m scraper.harvest --headed` and inspect `data/debug/01_loaded.png` and `data/debug/05_part_121_col1_scroll0.png` in an image editor. Hover over target elements to read pixel coordinates from the status bar.

---

## Notes

- The pipeline respects the FAA portal by using fixed scroll delays and does not make excessive concurrent requests.
- `.env` is excluded from version control. Never commit credentials.
- `data/operators.csv` and `data/faa_raw_dump.txt` are excluded from version control — regenerate them by running the pipeline.
- The `data/debug/` folder (viewport screenshots) is also excluded — it is created automatically during each harvest run and is useful for diagnosing OCR/coordinate issues.
