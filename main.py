"""
FAA Air Operator Data Pipeline — entry point.

Usage:
    python main.py
    python main.py --dry-run
    python main.py --cfr-parts 121,135
    python main.py --cfr-parts 135 --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys

from playwright.sync_api import sync_playwright

from config.settings import load_settings
from db.connection import get_connection, close_pool
from db.repository import upsert_operator, replace_dba_names, replace_aircraft
from scraper.browser import make_page
from scraper.faa_scraper import scrape_part
from scraper.robots import check_robots_compliance
from scraper.throttle import AdaptiveThrottle
from utils.logger import setup_logging
from utils.retry import make_retry


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FAA Air Operator Data Pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and log records without writing to the database.",
    )
    parser.add_argument(
        "--cfr-parts",
        type=str,
        default=None,
        metavar="PARTS",
        help="Comma-separated CFR parts to scrape (e.g. 121,135). Overrides .env CFR_PARTS.",
    )
    return parser.parse_args()


def run() -> None:
    args = _parse_args()
    settings = load_settings()

    if args.cfr_parts:
        cfr_parts = [int(p.strip()) for p in args.cfr_parts.split(",") if p.strip()]
    else:
        cfr_parts = settings.cfr_parts

    setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    logger.info("Pipeline starting", extra={"cfr_parts": cfr_parts, "dry_run": args.dry_run})

    # Robots compliance check — aborts if target URL is disallowed
    crawl_delay = check_robots_compliance(settings.user_agent)

    throttle = AdaptiveThrottle(settings.throttle_min, settings.throttle_max)
    throttle.apply_crawl_delay(crawl_delay)

    retry_fn = make_retry(settings)

    with sync_playwright() as pw:
        page, browser = make_page(settings, pw)
        try:
            for cfr_part in cfr_parts:
                logger.info("Scraping CFR Part", extra={"cfr_part": cfr_part})
                try:
                    records = retry_fn(scrape_part)(page, cfr_part, throttle, settings)
                except Exception:
                    logger.exception(
                        "Scrape failed for CFR part — skipping",
                        extra={"cfr_part": cfr_part},
                    )
                    continue

                logger.info(
                    "Scrape complete",
                    extra={"cfr_part": cfr_part, "record_count": len(records)},
                )

                if args.dry_run:
                    for rec in records:
                        logger.info(
                            "DRY RUN — operator",
                            extra={
                                "cert": rec.certificate_number,
                                "operator_name": rec.operator_name,
                                "aircraft_count": len(rec.aircraft),
                            },
                        )
                    continue

                with get_connection(settings) as conn:
                    for record in records:
                        try:
                            op_id = upsert_operator(conn, record)
                            replace_dba_names(conn, op_id, record.dba_names)
                            replace_aircraft(conn, op_id, record.aircraft)
                            conn.commit()
                            logger.info(
                                "Persisted operator",
                                extra={
                                    "cert": record.certificate_number,
                                    "operator_id": op_id,
                                },
                            )
                        except Exception:
                            conn.rollback()
                            logger.exception(
                                "Failed to persist operator — rolled back",
                                extra={"cert": record.certificate_number},
                            )
        finally:
            browser.close()
            close_pool()

    logger.info("Pipeline finished")


if __name__ == "__main__":
    sys.exit(run())
