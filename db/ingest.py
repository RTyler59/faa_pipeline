"""
Load data/operators.csv into the faa_operators PostgreSQL database.

Maps CSV columns to DB columns, converts types (empty string -> NULL,
string -> INTEGER/DATE), and upserts on certificate_number.
DBA names are stored in the operator_dba_names child table.

Usage:
    python -m db.ingest
    python -m db.ingest --csv data/operators.csv
    python -m db.ingest --dry-run
"""

import argparse
import csv
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_batch

from config.settings import load_settings

CSV_FILE = Path("data/operators.csv")

_UPSERT_SQL = """
    INSERT INTO air_operators (
        certificate_number, operator_name, issue_date, designator_code,
        cfr_part,
        ceo_name, ceo_street, ceo_city, ceo_state, ceo_zip,
        dir_operations, dir_maintenance, chief_pilot,
        pic_captains, inspectors, designated_inspectors,
        certificated_mechanics, noncertificated_mechanics, total_employees
    )
    VALUES (
        %(certificate_number)s, %(operator_name)s, %(issue_date)s, %(designator_code)s,
        %(cfr_part)s,
        %(ceo_name)s, %(ceo_street)s, %(ceo_city)s, %(ceo_state)s, %(ceo_zip)s,
        %(dir_operations)s, %(dir_maintenance)s, %(chief_pilot)s,
        %(pic_captains)s, %(inspectors)s, %(designated_inspectors)s,
        %(certificated_mechanics)s, %(noncertificated_mechanics)s, %(total_employees)s
    )
    ON CONFLICT (certificate_number) DO UPDATE SET
        operator_name             = EXCLUDED.operator_name,
        issue_date                = EXCLUDED.issue_date,
        designator_code           = EXCLUDED.designator_code,
        cfr_part                  = EXCLUDED.cfr_part,
        ceo_name                  = EXCLUDED.ceo_name,
        ceo_street                = EXCLUDED.ceo_street,
        ceo_city                  = EXCLUDED.ceo_city,
        ceo_state                 = EXCLUDED.ceo_state,
        ceo_zip                   = EXCLUDED.ceo_zip,
        dir_operations            = EXCLUDED.dir_operations,
        dir_maintenance           = EXCLUDED.dir_maintenance,
        chief_pilot               = EXCLUDED.chief_pilot,
        pic_captains              = EXCLUDED.pic_captains,
        inspectors                = EXCLUDED.inspectors,
        designated_inspectors     = EXCLUDED.designated_inspectors,
        certificated_mechanics    = EXCLUDED.certificated_mechanics,
        noncertificated_mechanics = EXCLUDED.noncertificated_mechanics,
        total_employees           = EXCLUDED.total_employees,
        updated_at                = NOW()
    RETURNING id, (xmax = 0) AS is_insert
"""


# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------

def _str(val: str) -> str | None:
    s = val.strip()
    return s or None


def _int(val: str) -> int | None:
    s = val.strip()
    return int(s) if s else None


def _date(val: str) -> str | None:
    s = val.strip()
    return s or None  # psycopg2 accepts ISO 'YYYY-MM-DD' strings directly


def _row_to_params(row: dict) -> dict:
    addr1 = row.get("address_line1", "").strip()
    addr2 = row.get("address_line2", "").strip()
    ceo_street = "\n".join(filter(None, [addr1, addr2])) or None

    return {
        "certificate_number":     row["cert_number"].strip(),
        "operator_name":          row["operator_name"].strip() or "(unknown)",
        "issue_date":             _date(row["issue_date"]),
        "designator_code":        _str(row["designator_code"]),
        "cfr_part":               _int(row["far_part"]),
        "ceo_name":               _str(row.get("ceo_name", "")),
        "ceo_street":             ceo_street,
        "ceo_city":               _str(row.get("city", "")),
        "ceo_state":              _str(row.get("state", "")),
        "ceo_zip":                _str(row.get("zip_code", "")),
        "dir_operations":         _str(row.get("dir_operations", "")),
        "dir_maintenance":        _str(row.get("dir_maintenance", "")),
        "chief_pilot":            _str(row.get("chief_pilot", "")),
        "pic_captains":           _int(row.get("pic_captains", "")),
        "inspectors":             _int(row.get("inspectors", "")),
        "designated_inspectors":  _int(row.get("designated_inspectors", "")),
        "certificated_mechanics": _int(row.get("certificated_mechanics", "")),
        "noncertificated_mechanics": _int(row.get("noncertificated_mechanics", "")),
        "total_employees":        _int(row.get("total_employees", "")),
    }


# ---------------------------------------------------------------------------
# Main ingest function
# ---------------------------------------------------------------------------

def ingest(csv_file: Path = CSV_FILE, dry_run: bool = False) -> int:
    """
    Load csv_file into the database.  Returns the number of rows processed.
    Uses per-row transactions so a single bad row doesn't abort the whole run.
    """
    with csv_file.open(encoding="utf-8", newline="") as f:
        csv_rows = list(csv.DictReader(f))

    print(f"Read {len(csv_rows)} rows from {csv_file}")

    if dry_run:
        print("\n[DRY RUN] First 10 rows that would be ingested:")
        for row in csv_rows[:10]:
            p = _row_to_params(row)
            dba = row.get("dba_names", "")
            print(
                f"  {p['certificate_number']:<12} "
                f"Part {p['cfr_part']}  "
                f"{(p['operator_name'] or '')[:35]:<35}  "
                f"DBA: {dba[:30] if dba else '—'}"
            )
        print(f"\n[DRY RUN] Would process {len(csv_rows)} rows. No DB writes made.")
        return len(csv_rows)

    settings = load_settings()
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        connect_timeout=10,
    )
    conn.autocommit = False

    inserted = updated = errors = 0

    try:
        for i, row in enumerate(csv_rows):
            params = _row_to_params(row)
            dba_names = list(dict.fromkeys(  # preserves order, removes duplicates
                n.strip()
                for n in row.get("dba_names", "").split("|")
                if n.strip()
            ))
            try:
                with conn.cursor() as cur:
                    cur.execute(_UPSERT_SQL, params)
                    operator_id, is_insert = cur.fetchone()

                    cur.execute(
                        "DELETE FROM operator_dba_names WHERE operator_id = %s",
                        (operator_id,),
                    )
                    if dba_names:
                        execute_batch(
                            cur,
                            "INSERT INTO operator_dba_names (operator_id, dba_name)"
                            " VALUES (%s, %s)",
                            [(operator_id, n) for n in dba_names],
                        )

                conn.commit()
                if is_insert:
                    inserted += 1
                else:
                    updated += 1

            except Exception as exc:
                conn.rollback()
                errors += 1
                print(
                    f"  ERROR row {i + 2} cert={row.get('cert_number', '?')}: {exc}",
                    file=sys.stderr,
                )

            if (i + 1) % 100 == 0:
                print(f"  {i + 1}/{len(csv_rows)} processed...")

    finally:
        conn.close()

    print(
        f"\nDone — inserted: {inserted}  updated: {updated}  errors: {errors}"
        f"  total: {inserted + updated + errors}"
    )
    return inserted + updated


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    ap = argparse.ArgumentParser(description="Ingest operators.csv -> PostgreSQL")
    ap.add_argument("--csv",     default=str(CSV_FILE), help="Path to operators.csv")
    ap.add_argument("--dry-run", action="store_true",   help="Print rows without writing to DB")
    args = ap.parse_args()
    count = ingest(Path(args.csv), dry_run=args.dry_run)
    sys.exit(0 if count > 0 else 1)


if __name__ == "__main__":
    _cli()
