"""
Parse data/faa_raw_dump.txt (produced by scraper/harvest.py) into
data/operators.csv.

harvest.py now OCRs each of the 3 Tableau columns independently and writes
them sequentially (column 1 top-to-bottom, then column 2, then column 3).
This means the raw text is a series of operator blocks in the same format
as the sample_data.md manual reference — one operator at a time, no
horizontal column interleaving.

Each operator block looks like:

    26 NORTH AVIATION INC
    d/b/a SKYSTREAM JET
    Certificate Number: 26NA882L
    Issue Date: 2007-07-17
    Designator Code: 26NA
    CHIEF EXECUTIVE OFFICER: DOUGLAS, DEMKO
    961 MARCON BLVD
    SUITE 106
    ALLENTOWN PA  18109
    DIR. OF OPERATIONS, PART 135: DEMKO, DOUGLAS R.
    DIR. OF MAINTENANCE, PART 135: DEL CORSO, DAVID
    CHIEF PILOT: ADORNATO, PHILIP FRANCIS
    PIC CAPTAINS: 11
    CERTIFICATED MECHANICS: 3
    TOTAL NUMBER OF EMPLOYEES: 27

Approach
--------
* Labeled fields are extracted with regex findall/finditer across the full
  section text.  Because the text is now sequential (not interleaved), the
  i-th cert number, i-th issue date, i-th designator code, etc. all belong
  to the same operator — zipping is correct.
* For CEO/address/personnel fields, a forward window is computed from each
  designator-code line to the next cert-number line.  All rich fields live
  in that window.
* Operator names are found by searching backward from each cert line.
* d/b/a values are found between the operator name and the cert line.

Usage
-----
    python -m scraper.text_parser
    python -m scraper.text_parser --in data/faa_raw_dump.txt --out data/operators.csv
"""

import argparse
import csv
import re
import sys
from dataclasses import astuple, dataclass, fields
from pathlib import Path

IN_FILE  = Path("data/faa_raw_dump.txt")
OUT_FILE = Path("data/operators.csv")

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Use [ :]+ (not [:\s]+) so patterns never cross a newline.
_CERT_RE  = re.compile(r"Certificate\s+Number[ :]+([A-Z0-9]{4,12})", re.I)
_ISSUE_RE = re.compile(r"Issue\s+Date[ :]+(\d{4}-\d{2}-\d{2})", re.I)
_DESIG_RE = re.compile(r"Designator\s+Code[ :]+([A-Z0-9]{3,6})", re.I)

_DBA_RE = re.compile(r"d/b/[al]a?\s+(.+?)(?=\s+d/b/[al]a?|\s*$)", re.I)

_CEO_RE         = re.compile(r"CHIEF\s+EXECUTIVE\s+OFFICER[ :]+(.+)", re.I)
_DIR_OPS_RE     = re.compile(r"DIR(?:ECTOR)?\.?\s+OF\s+OPERATIONS[^:]*:[ ]+(.+)", re.I)
_DIR_MX_RE      = re.compile(r"DIR(?:ECTOR)?\.?\s+OF\s+MAINTENANCE[^:]*:[ ]+(.+)", re.I)
_CHIEF_PILOT_RE = re.compile(r"CHIEF\s+PILOT[^:]*:[ ]+(.+)", re.I)
_PIC_RE         = re.compile(r"PIC\s+CAPTAINS[ :]+(\d+)", re.I)
_INSP_RE        = re.compile(r"(?<!DESIGNATED\s)INSPECTORS[ :]+(\d+)", re.I)
_DESIG_INSP_RE  = re.compile(r"DESIGNATED\s+INSPECTORS[ :]+(\d+)", re.I)
_CERT_MECH_RE   = re.compile(r"CERTIFICATED\s+MECHANICS[ :]+(\d+)", re.I)
_NONCERT_RE     = re.compile(r"NONCERTIFICATED\s+MECHANICS[ :]+(\d+)", re.I)
_TOTAL_EMP_RE   = re.compile(r"TOTAL\s+(?:NUMBER\s+OF\s+)?EMPLOYEES[ :]+(\d+)", re.I)

# City STATE  ZIP on a single line (2+ spaces between state and zip)
_CITY_STATE_ZIP_RE = re.compile(r"^(.+?)\s+([A-Z]{2})\s{2,}(\d{5}(?:-\d{4})?)$")

# Identify ALL-CAPS company-name lines
_NAME_RE        = re.compile(r"^[A-Z0-9][A-Z0-9 ,.\-&/']+$")
_COMPANY_END_RE = re.compile(
    r"\b(?:LLC|INC|CORP|LTD|GMBH|OYJ|APS|PTY|SRL|SAC|SPA|S\.A\.(?:S\.?)?)\.?\s*$",
    re.I,
)
_STREET_SUFFIX_RE = re.compile(
    r"\b(BLVD|BOULEVARD|STREET|AVENUE|AVE|ROAD|DRIVE|HIGHWAY|HWY"
    r"|SUITE|STE|FLOOR|FL|COURT|CT|LANE|LN|PLACE|PL|WAY)\s*$",
    re.I,
)
_STATE_ZIP_RE = re.compile(r"^(.+)\s+([A-Z]{2})\s{2,}(\d{5}(?:-\d{4})?)$")
_SKIP_NAME_RE = re.compile(
    r"Certificate|Issue\s+Date|Designator|Director|Chief|Officer|Pilot"
    r"|Mechanic|Inspector|Employee|Aircraft|Updated|Captain|TOTAL|PIC\s"
    r"|[A-Z]+-\d{3}",
    re.I,
)

# Lines that mark the start of the personnel / address section
_FIELD_START_RE = re.compile(
    r"^(DIR\.|DIRECTOR|CHIEF\s+EXECUTIVE|CHIEF\s+PILOT|PIC\s+CAPTAINS"
    r"|INSPECTORS|DESIGNATED|CERTIFICATED|NONCERTIFICATED|TOTAL)",
    re.I,
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class OperatorRow:
    far_part:                  str
    operator_name:             str
    dba_names:                 str
    cert_number:               str
    issue_date:                str
    designator_code:           str
    ceo_name:                  str
    address_line1:             str
    address_line2:             str
    city:                      str
    state:                     str
    zip_code:                  str
    dir_operations:            str
    dir_maintenance:           str
    chief_pilot:               str
    pic_captains:              str
    inspectors:                str
    designated_inspectors:     str
    certificated_mechanics:    str
    noncertificated_mechanics: str
    total_employees:           str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_name_line(line: str) -> bool:
    if not _NAME_RE.match(line) or len(line) < 5:
        return False
    if re.match(r"^\d{3,}", line) and not _COMPANY_END_RE.search(line):
        return False
    if _STREET_SUFFIX_RE.search(line):
        return False
    if _STATE_ZIP_RE.match(line):
        return False
    if re.match(r"^(SUITE|STE|FLOOR|UNIT|APT|RM)\b", line, re.I):
        return False
    if _SKIP_NAME_RE.search(line):
        return False
    return True


def _find_name_line(lines: list[str], cert_line_idx: int) -> str:
    for i in range(cert_line_idx - 1, max(-1, cert_line_idx - 16), -1):
        candidate = lines[i].strip()
        if candidate and _is_name_line(candidate):
            return candidate
    return ""


def _line_of(line_starts: list[int], pos: int) -> int:
    lo, hi = 0, len(line_starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if line_starts[mid] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _parse_address(fwd_lines: list[str], ceo_fwd_idx: int) -> tuple[str, str, str, str, str]:
    """
    Extract address_line1, address_line2, city, state, zip_code from the
    lines immediately following the CEO line.  Stops at the first labeled
    field (DIR., CHIEF PILOT, PIC, etc.).
    """
    addr_candidates: list[str] = []
    for line in fwd_lines[ceo_fwd_idx + 1:]:
        if not line:
            continue
        if _FIELD_START_RE.match(line):
            break
        addr_candidates.append(line)

    city = state = zip_code = addr1 = addr2 = ""
    csz_idx = -1
    for j, ac in enumerate(addr_candidates):
        m = _CITY_STATE_ZIP_RE.match(ac)
        if m:
            csz_idx  = j
            city     = m.group(1).strip()
            state    = m.group(2)
            zip_code = m.group(3)
            break

    if csz_idx >= 0:
        addr1 = addr_candidates[0] if csz_idx > 0 else ""
        addr2 = addr_candidates[1] if csz_idx > 1 else ""
    elif addr_candidates:
        addr1 = addr_candidates[0]

    return addr1, addr2, city, state, zip_code


def _parse_section(far_part: str, text: str) -> list[OperatorRow]:
    """
    Parse one FAR PART section into OperatorRow records.

    With column-separated OCR, each operator's fields appear sequentially.
    The i-th cert/issue/desig match all belong to the same operator.
    Forward windows (desig line -> next cert line) contain CEO/address/
    personnel data.
    """
    lines = text.split("\n")

    line_starts: list[int] = []
    offset = 0
    for line in lines:
        line_starts.append(offset)
        offset += len(line) + 1

    cert_matches  = list(_CERT_RE.finditer(text))
    issue_matches = list(_ISSUE_RE.finditer(text))
    desig_matches = list(_DESIG_RE.finditer(text))

    n = min(len(cert_matches), len(issue_matches), len(desig_matches))

    rows: list[OperatorRow] = []

    for i in range(n):
        cert_m   = cert_matches[i]
        cert_num = cert_m.group(1).upper()
        issue    = issue_matches[i].group(1)
        desig_m  = desig_matches[i]
        desig    = desig_m.group(1).upper()

        cert_line_idx  = _line_of(line_starts, cert_m.start())
        desig_line_idx = _line_of(line_starts, desig_m.start())

        # Forward window: from after the designator line to just before the
        # next operator's cert line (or end of section).
        next_cert_line = (
            _line_of(line_starts, cert_matches[i + 1].start())
            if i + 1 < n else len(lines)
        )
        fwd_lines = [l.strip() for l in lines[desig_line_idx + 1 : next_cert_line]]

        # Operator name (search backward from cert line)
        operator_name = _find_name_line(lines, cert_line_idx)

        # d/b/a names (lines between operator name and cert line)
        dba_names: list[str] = []
        for li in range(max(0, cert_line_idx - 8), cert_line_idx):
            for m_dba in _DBA_RE.finditer(lines[li]):
                val = m_dba.group(1).strip().rstrip(".,")
                if val and len(val) > 2:
                    dba_names.append(val)

        fwd_text = "\n".join(fwd_lines)

        # CEO name and address
        ceo_m    = _CEO_RE.search(fwd_text)
        ceo_name = ceo_m.group(1).strip() if ceo_m else ""

        addr1 = addr2 = city = state = zip_code = ""
        if ceo_m:
            ceo_fwd_line = fwd_text[: ceo_m.start()].count("\n")
            addr1, addr2, city, state, zip_code = _parse_address(fwd_lines, ceo_fwd_line)

        def _val(m: re.Match | None) -> str:
            return m.group(1).strip() if m else ""

        rows.append(OperatorRow(
            far_part                  = far_part,
            operator_name             = operator_name,
            dba_names                 = "|".join(dba_names),
            cert_number               = cert_num,
            issue_date                = issue,
            designator_code           = desig,
            ceo_name                  = ceo_name,
            address_line1             = addr1,
            address_line2             = addr2,
            city                      = city,
            state                     = state,
            zip_code                  = zip_code,
            dir_operations            = _val(_DIR_OPS_RE.search(fwd_text)),
            dir_maintenance           = _val(_DIR_MX_RE.search(fwd_text)),
            chief_pilot               = _val(_CHIEF_PILOT_RE.search(fwd_text)),
            pic_captains              = _val(_PIC_RE.search(fwd_text)),
            inspectors                = _val(_INSP_RE.search(fwd_text)),
            designated_inspectors     = _val(_DESIG_INSP_RE.search(fwd_text)),
            certificated_mechanics    = _val(_CERT_MECH_RE.search(fwd_text)),
            noncertificated_mechanics = _val(_NONCERT_RE.search(fwd_text)),
            total_employees           = _val(_TOTAL_EMP_RE.search(fwd_text)),
        ))

    # Deduplicate by cert_number (scroll overlap can produce duplicate lines)
    seen: set[str] = set()
    deduped: list[OperatorRow] = []
    for row in rows:
        if row.cert_number not in seen:
            seen.add(row.cert_number)
            deduped.append(row)

    return deduped


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse(in_file: Path = IN_FILE, out_file: Path = OUT_FILE) -> int:
    """Parse in_file and write out_file.  Returns the number of rows written."""
    text = in_file.read_text(encoding="utf-8")

    parts = re.split(r"=== FAR PART (\d+) ===", text)
    if len(parts) < 3:
        print(
            f"ERROR: No '=== FAR PART N ===' sections found in {in_file}.\n"
            "Run scraper/harvest.py first to generate the raw dump."
        )
        return 0

    all_rows: list[OperatorRow] = []
    it = iter(parts[1:])
    for part, body in zip(it, it):
        rows = _parse_section(part.strip(), body)
        all_rows.extend(rows)
        print(f"  Part {part.strip()}: {len(rows)} operators parsed")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    field_names = [f.name for f in fields(OperatorRow)]
    with out_file.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(field_names)
        for row in all_rows:
            writer.writerow(astuple(row))

    print(f"\nWrote {len(all_rows)} rows -> {out_file}")
    return len(all_rows)


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Parse faa_raw_dump.txt -> operators.csv")
    ap.add_argument("--in",  dest="in_file",  default=str(IN_FILE))
    ap.add_argument("--out", dest="out_file", default=str(OUT_FILE))
    args = ap.parse_args()
    count = parse(Path(args.in_file), Path(args.out_file))
    sys.exit(0 if count > 0 else 1)


if __name__ == "__main__":
    _cli()
