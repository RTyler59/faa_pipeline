from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    throttle_min: float
    throttle_max: float
    user_agent: str
    headless: bool
    playwright_timeout: int
    retry_max_attempts: int
    retry_wait_min: int
    retry_wait_max: int
    log_level: str
    cfr_parts: List[int]


def load_settings() -> Settings:
    load_dotenv()

    def req(key: str) -> str:
        val = os.environ.get(key)
        if val is None:
            raise EnvironmentError(f"Required environment variable '{key}' is not set.")
        return val

    raw_parts = os.getenv("CFR_PARTS", "121,125,129,133,135")
    cfr_parts = [int(p.strip()) for p in raw_parts.split(",") if p.strip()]

    return Settings(
        db_host=req("DB_HOST"),
        db_port=int(os.getenv("DB_PORT", "5432")),
        db_name=req("DB_NAME"),
        db_user=req("DB_USER"),
        db_password=req("DB_PASS"),
        throttle_min=float(os.getenv("THROTTLE_MIN", "2.0")),
        throttle_max=float(os.getenv("THROTTLE_MAX", "5.0")),
        user_agent=os.getenv(
            "USER_AGENT",
            "FAA-DataPipeline/1.0 (+https://github.com/yourorg/faa-pipeline)",
        ),
        headless=os.getenv("HEADLESS", "true").lower() == "true",
        playwright_timeout=int(os.getenv("PLAYWRIGHT_TIMEOUT", "30000")),
        retry_max_attempts=int(os.getenv("RETRY_MAX_ATTEMPTS", "3")),
        retry_wait_min=int(os.getenv("RETRY_WAIT_MIN_SECONDS", "4")),
        retry_wait_max=int(os.getenv("RETRY_WAIT_MAX_SECONDS", "60")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        cfr_parts=cfr_parts,
    )
