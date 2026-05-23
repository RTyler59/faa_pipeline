from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

from config.settings import Settings

logger = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None


def get_pool(settings: Settings) -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            connect_timeout=10,
        )
        logger.info("Database connection pool created", extra={"db_host": settings.db_host})
    return _pool


@contextmanager
def get_connection(settings: Settings) -> Generator:
    pool = get_pool(settings)
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("Database connection pool closed")
