-- FAA Air Operator Data Pipeline
-- Idempotent schema — safe to run multiple times against an existing database.
-- Apply with: psql -U <user> -d <dbname> -f schema.sql

-- ─────────────────────────────────────────────────────────────────────────────
-- Air Operators
-- Primary record keyed on certificate_number (FAA's natural unique identifier).
-- All personnel/count columns are nullable because they vary by CFR part:
--   inspectors + designated_inspectors appear on Part 121/129 records only.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS air_operators (
    id                        SERIAL          PRIMARY KEY,
    certificate_number        VARCHAR(20)     NOT NULL,
    operator_name             TEXT            NOT NULL,
    issue_date                DATE,
    designator_code           VARCHAR(10),
    cfr_part                  SMALLINT,
    fsdo_code                 VARCHAR(20),
    ceo_name                  TEXT,
    ceo_street                TEXT,
    ceo_city                  TEXT,
    ceo_state                 CHAR(2),
    ceo_zip                   VARCHAR(10),
    dir_operations            TEXT,
    dir_maintenance           TEXT,
    chief_pilot               TEXT,
    pic_captains              INTEGER,
    inspectors                INTEGER,
    designated_inspectors     INTEGER,
    certificated_mechanics    INTEGER,
    noncertificated_mechanics INTEGER,
    total_employees           INTEGER,
    scraped_at                TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_certificate UNIQUE (certificate_number)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- DBA Names (0-to-N per operator)
-- Stored in a separate table rather than an array/JSONB so that each alias
-- is independently queryable (e.g. WHERE dba_name ILIKE '%delta%').
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS operator_dba_names (
    id              SERIAL  PRIMARY KEY,
    operator_id     INTEGER NOT NULL
                    REFERENCES air_operators(id)
                    ON DELETE CASCADE,
    dba_name        TEXT    NOT NULL,
    CONSTRAINT uq_operator_dba UNIQUE (operator_id, dba_name)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Aircraft Inventory (0-to-N per operator)
-- Populated from the "Show Aircraft" JS toggle on the FAA portal.
-- Make/model/series uniqueness scoped to the parent operator.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aircraft (
    id              SERIAL  PRIMARY KEY,
    operator_id     INTEGER NOT NULL
                    REFERENCES air_operators(id)
                    ON DELETE CASCADE,
    make            TEXT,
    model           TEXT,
    series          TEXT,
    CONSTRAINT uq_operator_aircraft UNIQUE (operator_id, make, model, series)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────────────────────────────────────

-- Fast filter by CFR part (most common analytical query)
CREATE INDEX IF NOT EXISTS idx_air_operators_cfr_part
    ON air_operators (cfr_part);

-- Full-text search on operator name for marketing lookups
CREATE INDEX IF NOT EXISTS idx_air_operators_name_fts
    ON air_operators USING gin (to_tsvector('english', operator_name));

-- Fast child-row lookup by parent (used by UPSERT logic in repository.py)
CREATE INDEX IF NOT EXISTS idx_dba_names_operator_id
    ON operator_dba_names (operator_id);

CREATE INDEX IF NOT EXISTS idx_aircraft_operator_id
    ON aircraft (operator_id);
