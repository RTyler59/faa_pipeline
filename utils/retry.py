import logging

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from config.settings import Settings

logger = logging.getLogger(__name__)


def make_retry(settings: Settings):
    """Return a tenacity retry decorator configured from Settings."""
    return retry(
        wait=wait_exponential(
            multiplier=1,
            min=settings.retry_wait_min,
            max=settings.retry_wait_max,
        ),
        stop=stop_after_attempt(settings.retry_max_attempts),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
