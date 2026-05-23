from __future__ import annotations

import dataclasses
import logging
from typing import List

from scraper.parser import OperatorRecord

logger = logging.getLogger(__name__)


def upsert_operator(conn, record: OperatorRecord) -> int:
    """Insert or update an air_operators row. Returns the database id."""
    sql = """
        INSERT INTO air_operators (
            certificate_number, operator_name, issue_date, designator_code,
            cfr_part, fsdo_code,
            ceo_name, ceo_street, ceo_city, ceo_state, ceo_zip,
            dir_operations, dir_maintenance, chief_pilot,
            pic_captains, inspectors, designated_inspectors,
            certificated_mechanics, noncertificated_mechanics, total_employees
        )
        VALUES (
            %(certificate_number)s, %(operator_name)s, %(issue_date)s, %(designator_code)s,
            %(cfr_part)s, %(fsdo_code)s,
            %(ceo_name)s, %(ceo_street)s, %(ceo_city)s, %(ceo_state)s, %(ceo_zip)s,
            %(dir_operations)s, %(dir_maintenance)s, %(chief_pilot)s,
            %(pic_captains)s, %(inspectors)s, %(designated_inspectors)s,
            %(certificated_mechanics)s, %(noncertificated_mechanics)s, %(total_employees)s
        )
        ON CONFLICT (certificate_number)
        DO UPDATE SET
            operator_name             = EXCLUDED.operator_name,
            issue_date                = EXCLUDED.issue_date,
            designator_code           = EXCLUDED.designator_code,
            cfr_part                  = EXCLUDED.cfr_part,
            fsdo_code                 = EXCLUDED.fsdo_code,
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
        RETURNING id
    """
    d = dataclasses.asdict(record)
    with conn.cursor() as cur:
        cur.execute(sql, d)
        row = cur.fetchone()
    return row[0]


def replace_dba_names(conn, operator_id: int, dba_names: List[str]) -> None:
    """Replace all DBA names for an operator within the current transaction."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM operator_dba_names WHERE operator_id = %s",
            (operator_id,),
        )
        if dba_names:
            cur.executemany(
                "INSERT INTO operator_dba_names (operator_id, dba_name) VALUES (%s, %s)",
                [(operator_id, name) for name in dba_names],
            )


def replace_aircraft(conn, operator_id: int, aircraft: List[dict]) -> None:
    """Replace all aircraft rows for an operator within the current transaction."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM aircraft WHERE operator_id = %s",
            (operator_id,),
        )
        if aircraft:
            cur.executemany(
                "INSERT INTO aircraft (operator_id, make, model, series) VALUES (%s, %s, %s, %s)",
                [
                    (operator_id, a.get("make"), a.get("model"), a.get("series"))
                    for a in aircraft
                ],
            )
