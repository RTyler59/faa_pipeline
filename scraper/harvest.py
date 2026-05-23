"""
Harvest FAA Air Operator data from the Tableau dashboard using:
  1. Canvas coordinate mouse clicks to select Show Aircraft and FAR parts.
  2. A scroll-and-OCR loop that walks the data panel from top to bottom,
     taking a cropped screenshot at each position and running Tesseract
     to extract the visible operator text.

Prerequisites (one-time setup):
  pip install pillow pytesseract
  Install Tesseract OCR engine from https://github.com/UB-Mannheim/tesseract/wiki
  Default Windows path: C:\\Users\\rickg\\AppData\\Local\\Programs\\Tesseract-OCR\\tesseract.exe
  If installed elsewhere, update TESSERACT_CMD below.

Run headed first to verify coordinate calibration:
    python -m scraper.harvest --headed

Then headless once confirmed:
    python -m scraper.harvest

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  COORDINATE CALIBRATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
All (x, y) values are browser-viewport pixels at 1280 × 800.
Open data/debug/01_loaded.png in an image editor, hover over the
target element, and read the pixel position from the status bar.
Update the constant, re-run --headed, and check the debug screenshots.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import io
import sys
import time
from pathlib import Path

import pytesseract
from PIL import Image
from playwright.sync_api import Page, sync_playwright

# ── Tesseract engine path (Windows default) ───────────────────────────────────
# ADJUST if Tesseract is installed to a different directory.
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Users\rickg\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
)

# ── destination ───────────────────────────────────────────────────────────────
DASHBOARD_URL = (
    "https://explore.dot.gov/t/FAA/views/AVInfo_AirOperators/AirOperators"
)
FAR_PARTS = [121, 125, 129, 133, 135]
OUT       = Path("data/faa_raw_dump.txt")
DEBUG_DIR = Path("data/debug")

# ── timing ────────────────────────────────────────────────────────────────────
LOAD_WAIT           = 12   # seconds after page.goto before any interaction
SHOW_AIRCRAFT_WAIT  =  5   # extra seconds after load for Show Aircraft to appear
RENDER_WAIT         =  5   # seconds after each FAR-part click for canvas to repaint
SCROLL_SETTLE       =  1.5 # seconds between scroll steps for canvas to redraw
SCROLL_MAX          = 350  # hard cap on scroll iterations per FAR part

# ── browser ───────────────────────────────────────────────────────────────────
VIEWPORT = {"width": 1280, "height": 800}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 FAA-Pipeline/1.0"
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COORDS — calibrated for 1280 × 800.
#  Adjust values and rerun --headed to verify.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# "Show Aircraft" checkbox in the top navigation / filter bar.
SHOW_AIRCRAFT_XY = (759, 51)   # ADJUST: x=button center, y=button row

# FAR-part bar marks in the "Operator FAR" chart.
# y=112 is the vertical midpoint of the bar row.
FAR_PART_COORDS = {
    121: (356, 112),   # ADJUST: leftmost bar
    125: (448, 112),   # ADJUST: second bar
    129: (540, 112),   # ADJUST: third bar
    133: (631, 112),   # ADJUST: fourth bar
    135: (712, 112),   # ADJUST: rightmost bar
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DATA PANEL / SCROLL GEOMETRY
#
#  The scrollbar sits at x=996, spanning y=155 to y=773 (618 px).
#  The data panel occupies the region to the left of the scrollbar.
#
#  DATA_PANEL_CROP  — PIL crop box (left, top, right, bottom) applied
#                     to each full-page screenshot before OCR.
#                     Keep right edge inside the scrollbar (< 996).
#
#  SCROLL_XY        — x,y coordinates inside the data panel where the
#                     mouse wheel event is sent.  Must land on the
#                     canvas, not on the scrollbar or toolbar.
#
#  SCROLL_STEP      — pixels scrolled per wheel event.  A value equal
#                     to roughly 90 % of the panel height ensures each
#                     new viewport has minimal overlap with the previous
#                     one while not skipping any rows.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DATA_PANEL_CROP         = (20, 155, 985, 773)   # ADJUST: (left, top, right, bottom)
DATA_PANEL_TOP_LEFT_XY  = (50, 165)             # ADJUST: first row of the data field
SCROLL_XY               = (500, 460)            # ADJUST: center of panel for wheel events
SCROLL_STEP             = 550                   # ADJUST: deltaY per mouse-wheel event
SCROLL_RESET_WAIT       =  3.0 # seconds after wheel-up reset for canvas to settle

# Split the data panel into N_COLUMNS vertical strips so each column is OCR'd
# independently.  COLUMN_DIVIDERS lists the x-offsets (relative to the left
# edge of DATA_PANEL_CROP) where each column boundary falls.  Place each
# divider in the middle of the white gap between adjacent Tableau columns.
#
# Calibration: run with --headed, then inspect data/debug/05_part_*_crop_scroll0.png.
# Use _find_column_dividers() below to re-measure from the screenshot.
#
# Gap analysis on 05_part_121_crop_scroll0.png (965 px wide crop):
#   Gap 1 (between col 1 and col 2): crop x = 410–462  → divider at 436
#   Gap 2 (between col 2 and col 3): crop x = 626–718  → divider at 672
N_COLUMNS       = 3
COLUMN_DIVIDERS = [436, 672]   # ADJUST: crop-relative x of each column boundary

_pl, _pt, _pr, _pb = DATA_PANEL_CROP
_bounds = [0] + COLUMN_DIVIDERS + [_pr - _pl]
COLUMN_CROPS = [
    (_pl + _bounds[i], _pt, _pl + _bounds[i + 1], _pb)
    for i in range(N_COLUMNS)
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _screenshot(page: Page, name: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(DEBUG_DIR / f"{name}.png"))
        print(f"  [screenshot] data/debug/{name}.png")
    except Exception as e:
        print(f"  [screenshot] skipped — {e}")


def _click_canvas(page: Page, x: int, y: int, label: str) -> None:
    print(f"  Clicking {label} at ({x}, {y})")
    page.mouse.move(x, y)
    time.sleep(0.3)
    page.mouse.click(x, y)


def _ocr_viewport(page: Page) -> list[str]:
    """
    Take a full-page screenshot and OCR each column strip separately.
    Returns one OCR string per column (len == N_COLUMNS).
    Splitting columns before OCR prevents Tesseract from interleaving text
    across all three columns into a single garbled output stream.
    """
    raw_png = page.screenshot()
    img = Image.open(io.BytesIO(raw_png))
    results: list[str] = []
    for crop_box in COLUMN_CROPS:
        crop = img.crop(crop_box)
        w, h = crop.size
        crop = crop.resize((w * 2, h * 2), Image.LANCZOS)
        results.append(pytesseract.image_to_string(crop, config="--psm 6 --oem 3"))
    return results


def _scroll_and_capture(page: Page, part: int) -> str:
    """
    Scroll the data panel from top to bottom, OCR each column of every viewport
    separately, and return the combined text with columns written sequentially
    (col 1 top-to-bottom, then col 2, then col 3).

    Stops when all column OCR outputs are identical to the previous step
    (canvas no longer scrolling).
    """
    col_lines: list[list[str]] = [[] for _ in COLUMN_CROPS]
    prev_texts: list[str | None] = [None] * N_COLUMNS

    for i in range(SCROLL_MAX):
        texts = _ocr_viewport(page)

        if all(t == p for t, p in zip(texts, prev_texts)):
            print(f"  Bottom reached after {i} scroll steps")
            break

        for col_idx, text in enumerate(texts):
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            col_lines[col_idx].extend(lines)

        total = sum(len(c) for c in col_lines)
        print(f"  Scroll {i + 1:>3}: {total:>5} total lines across {N_COLUMNS} columns")

        if i == 0:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            raw_png = page.screenshot()
            img = Image.open(io.BytesIO(raw_png))
            for j, crop_box in enumerate(COLUMN_CROPS):
                img.crop(crop_box).save(
                    str(DEBUG_DIR / f"05_part_{part}_col{j + 1}_scroll0.png")
                )

        prev_texts = texts

        page.mouse.move(SCROLL_XY[0], SCROLL_XY[1])
        page.mouse.wheel(0, SCROLL_STEP)
        time.sleep(SCROLL_SETTLE)

    # Concatenate columns sequentially so each column reads top-to-bottom
    # as a continuous single-column stream (no horizontal interleaving).
    all_lines: list[str] = []
    for col in col_lines:
        all_lines.extend(col)
        all_lines.append("")   # blank separator between column streams
    return "\n".join(all_lines)


# ── main flow ─────────────────────────────────────────────────────────────────

def harvest(headless: bool = False) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            viewport=VIEWPORT,
            user_agent=_USER_AGENT,
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = ctx.new_page()

        # ── 1. Load dashboard ────────────────────────────────────────────────
        print("Navigating to dashboard…")
        try:
            page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=90_000)
        except Exception:
            pass    # Tableau rarely reaches networkidle; continue if page loaded

        print(f"Waiting {LOAD_WAIT}s for initial canvas render…")
        time.sleep(LOAD_WAIT)
        _screenshot(page, "01_loaded")

        # ── 2. Click "Show Aircraft" toggle ──────────────────────────────────
        # Wait an extra SHOW_AIRCRAFT_WAIT seconds beyond the initial load
        # because the checkbox renders after the main canvas is painted.
        print(f"Waiting {SHOW_AIRCRAFT_WAIT}s for Show Aircraft checkbox to appear…")
        time.sleep(SHOW_AIRCRAFT_WAIT)
        _click_canvas(page, *SHOW_AIRCRAFT_XY, "Show Aircraft toggle")
        time.sleep(2)
        _screenshot(page, "02_aircraft_toggle")

        # ── 3. Loop through FAR parts ────────────────────────────────────────
        with OUT.open("w", encoding="utf-8") as fh:
            for part in FAR_PARTS:
                print(f"\n── FAR Part {part} ──────────────────────────────")

                # Switch to this FAR part
                _click_canvas(page, *FAR_PART_COORDS[part], f"FAR Part {part} mark")
                print(f"  Waiting {RENDER_WAIT}s for canvas to repaint…")
                time.sleep(RENDER_WAIT)
                _screenshot(page, f"03_part_{part}_selected")

                # Reset scroll to top via mouse wheel — no click in the data field.
                # Clicking the data field after render causes the first records to be
                # skipped; wheel-only reset avoids that entirely.
                page.mouse.move(SCROLL_XY[0], SCROLL_XY[1])
                page.mouse.wheel(0, -(SCROLL_STEP * SCROLL_MAX))
                print(f"  Waiting {SCROLL_RESET_WAIT}s for scroll reset to settle…")
                time.sleep(SCROLL_RESET_WAIT)

                # Scroll through the panel and OCR every viewport
                raw_text = _scroll_and_capture(page, part)

                total_lines = raw_text.count("\n") + 1 if raw_text.strip() else 0
                print(f"  Total lines captured for Part {part}: {total_lines}")

                fh.write(f"=== FAR PART {part} ===\n")
                fh.write(raw_text.strip())
                fh.write("\n\n")

        browser.close()

    print(f"\nDone. Raw text → {OUT}")
    print(f"Debug screenshots → {DEBUG_DIR}/")


if __name__ == "__main__":
    harvest(headless="--headed" not in sys.argv)
