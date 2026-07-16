"""F2 — Normalize: load raw CSVs into DuckDB with a unified schema.

Tables produced:
  projects(project_id, programme, acronym, title, objective, start_date,
           end_date, total_cost, url, coordinator_name, coordinator_country,
           coordinator_activity_type, n_partners, status, source_link)
  deliverables(project_id, title, deliverable_type, url)

CORDIS column names occasionally shift (PRD §9), so required columns are
resolved through candidate lists and missing ones fail loudly.
"""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from . import config

log = logging.getLogger(__name__)

# column-role -> candidate CORDIS header names, first match wins
PROJECT_COLUMNS = {
    "project_id": ["id", "projectID"],
    "acronym": ["acronym"],
    "status": ["status"],
    "title": ["title"],
    "objective": ["objective"],
    "start_date": ["startDate"],
    "end_date": ["endDate"],
    "total_cost": ["totalCost"],
}
# optional in some bundles (H2020 had projectUrl in project.csv, HORIZON not)
PROJECT_URL_CANDIDATES = ["projectUrl", "url", "projectWebsite"]

ORG_COLUMNS = {
    "project_id": ["projectID"],
    "name": ["name"],
    "country": ["country"],
    "activity_type": ["activityType"],
    "role": ["role"],
}
ORG_URL_CANDIDATES = ["organizationURL", "organisationURL"]

DELIVERABLE_COLUMNS = {
    "project_id": ["projectID"],
    "title": ["title"],
    "deliverable_type": ["deliverableType", "type"],
    "url": ["url"],
}


def _read_csv_rel(con: duckdb.DuckDBPyConnection, path: Path):
    """CORDIS CSVs are semicolon-delimited, quoted, UTF-8."""
    return con.read_csv(
        str(path), delimiter=";", header=True, quotechar='"',
        all_varchar=True, ignore_errors=True,
    )


def _resolve(available: list[str], mapping: dict[str, list[str]], source: str) -> dict[str, str]:
    lower = {c.lower(): c for c in available}
    resolved, missing = {}, []
    for role, candidates in mapping.items():
        hit = next((lower[c.lower()] for c in candidates if c.lower() in lower), None)
        if hit is None:
            missing.append(f"{role} (tried {candidates})")
        else:
            resolved[role] = hit
    if missing:
        raise RuntimeError(
            f"schema drift in {source}: missing columns {missing}; "
            f"available: {available}"
        )
    return resolved


def _optional(available: list[str], candidates: list[str]) -> str | None:
    lower = {c.lower(): c for c in available}
    return next((lower[c.lower()] for c in candidates if c.lower() in lower), None)


def normalize(
    con: duckdb.DuckDBPyConnection,
    project_csv: Path,
    organization_csv: Path,
    deliverables_csv: Path | None,
    programme: str = "HORIZON",
) -> None:
    """Build unified projects + deliverables tables for one programme."""
    proj_rel = _read_csv_rel(con, project_csv)
    pc = _resolve(proj_rel.columns, PROJECT_COLUMNS, project_csv.name)
    url_col = _optional(proj_rel.columns, PROJECT_URL_CANDIDATES)
    url_expr = f'NULLIF(TRIM(p."{url_col}"), \'\')' if url_col else "NULL"

    org_rel = _read_csv_rel(con, organization_csv)
    oc = _resolve(org_rel.columns, ORG_COLUMNS, organization_csv.name)
    org_url_col = _optional(org_rel.columns, ORG_URL_CANDIDATES)
    org_url_expr = f'NULLIF(TRIM(o."{org_url_col}"), \'\')' if org_url_col else "NULL"

    con.register("raw_project", proj_rel)
    con.register("raw_org", org_rel)

    con.execute(f"""
        CREATE OR REPLACE TABLE projects AS
        WITH coord AS (
            SELECT o."{oc['project_id']}" AS project_id,
                   any_value(o."{oc['name']}") AS coordinator_name,
                   any_value(o."{oc['country']}") AS coordinator_country,
                   any_value(o."{oc['activity_type']}") AS coordinator_activity_type,
                   any_value({org_url_expr}) AS coordinator_url
            FROM raw_org o
            WHERE lower(o."{oc['role']}") = 'coordinator'
            GROUP BY 1
        ),
        partners AS (
            SELECT o."{oc['project_id']}" AS project_id,
                   count(*) AS n_partners
            FROM raw_org o GROUP BY 1
        )
        SELECT
            p."{pc['project_id']}"                    AS project_id,
            '{programme}'                             AS programme,
            p."{pc['acronym']}"                       AS acronym,
            p."{pc['title']}"                         AS title,
            p."{pc['objective']}"                     AS objective,
            TRY_CAST(p."{pc['start_date']}" AS DATE)  AS start_date,
            TRY_CAST(p."{pc['end_date']}" AS DATE)    AS end_date,
            TRY_CAST(REPLACE(p."{pc['total_cost']}", ',', '.') AS DOUBLE)
                                                      AS total_cost,
            COALESCE({url_expr}, c.coordinator_url)   AS url,
            c.coordinator_name,
            c.coordinator_country,
            c.coordinator_activity_type,
            COALESCE(pa.n_partners, 1)                AS n_partners,
            p."{pc['status']}"                        AS status,
            'https://cordis.europa.eu/project/id/' || p."{pc['project_id']}"
                                                      AS source_link
        FROM raw_project p
        LEFT JOIN coord c    ON c.project_id  = p."{pc['project_id']}"
        LEFT JOIN partners pa ON pa.project_id = p."{pc['project_id']}"
    """)
    con.unregister("raw_project")
    con.unregister("raw_org")

    if deliverables_csv and deliverables_csv.exists():
        del_rel = _read_csv_rel(con, deliverables_csv)
        dc = _resolve(del_rel.columns, DELIVERABLE_COLUMNS, deliverables_csv.name)
        con.register("raw_del", del_rel)
        con.execute(f"""
            CREATE OR REPLACE TABLE deliverables AS
            SELECT d."{dc['project_id']}"        AS project_id,
                   d."{dc['title']}"             AS title,
                   d."{dc['deliverable_type']}"  AS deliverable_type,
                   NULLIF(TRIM(d."{dc['url']}"), '') AS url
            FROM raw_del d
        """)
        con.unregister("raw_del")
    else:
        con.execute("""
            CREATE TABLE IF NOT EXISTS deliverables (
                project_id VARCHAR, title VARCHAR,
                deliverable_type VARCHAR, url VARCHAR
            )
        """)

    n = con.execute("SELECT count(*) FROM projects").fetchone()[0]
    nd = con.execute("SELECT count(*) FROM deliverables").fetchone()[0]
    log.info("normalized: %d projects, %d deliverables", n, nd)
