"""F3 — Filter & score: S1 gate, S2–S4 signals, modifiers, prospects table.

The Distress Score (0–100) is the core IP (PRD §5). The Fit flag is kept
out of the distress score and only affects outreach priority ordering.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

import duckdb
import pandas as pd

from . import config

log = logging.getLogger(__name__)


@dataclass
class UrlStatus:
    """Result of an F4 liveness check (see enrich.py)."""
    state: str          # 'dead' | 'parked' | 'alive_no_match' | 'alive_match'
    detail: str = ""


@dataclass
class ScoreBreakdown:
    s2: int = 0
    s3: int = 0
    s4: int = 0
    modifiers: int = 0
    matched_keywords: list[str] = field(default_factory=list)
    fit: bool = False

    @property
    def total(self) -> int:
        return self.s2 + self.s3 + self.s4 + self.modifiers

    @property
    def priority(self) -> int:
        """Outreach ordering only — fit bonus never enters the distress score."""
        return self.total + (config.FIT_PTS if self.fit else 0)


def s1_gate(title: str | None, objective: str | None,
            deliverable_titles: list[str] | None = None) -> list[str]:
    """Return matched lexicon keywords (empty list = project fails the gate)."""
    text = " ".join(
        t for t in [title or "", objective or "", *(deliverable_titles or [])] if t
    )
    return sorted({m.group(0).lower() for m in config.LEXICON.finditer(text)})


def elapsed_fraction(start: dt.date | None, end: dt.date | None,
                     today: dt.date) -> float | None:
    if not start or not end or end <= start:
        return None
    return (today - start).days / (end - start).days


def s2_timeline(elapsed: float | None) -> int:
    if elapsed is None:
        return 0
    for lo, hi, pts in config.S2_BANDS:
        if lo <= elapsed <= hi:
            return pts
    return 0


def s3_absence(elapsed: float | None, url: str | None,
               url_status: UrlStatus | None) -> int:
    if elapsed is None or elapsed <= config.S3_MIN_ELAPSED:
        return 0
    pts = 0
    if not url:
        pts += config.S3_NO_URL
    elif url_status is not None:
        if url_status.state in ("dead", "parked"):
            pts += config.S3_URL_DEAD
        elif url_status.state == "alive_no_match":
            pts += config.S3_URL_NO_MATCH
    return min(pts, config.S3_CAP)


def s4_deliverable_gap(elapsed: float | None, programme: str,
                       planned_digital: int, published_digital: int) -> int:
    """Horizon only: promised digital deliverables vs. what's published."""
    if programme != "HORIZON" or elapsed is None or elapsed <= config.S4_MIN_ELAPSED:
        return 0
    if planned_digital == 0:
        return 0
    if published_digital == 0:
        return config.S4_NOTHING_PUBLISHED
    if published_digital < planned_digital:
        return config.S4_PARTIAL
    return 0


def modifiers(n_partners: int | None, activity_type: str | None) -> int:
    pts = 0
    if n_partners is not None and n_partners <= config.SMALL_CONSORTIUM_MAX:
        pts += config.SMALL_CONSORTIUM_PTS
    if activity_type and activity_type.strip().upper() in config.NGO_ACTIVITY_TYPES:
        pts += config.NGO_COORDINATOR_PTS
    return pts


def latest_allowed_start(today: dt.date) -> dt.date:
    """Eligibility cutoff: the project must have started no later than
    Dec 31 of the previous year."""
    return dt.date(today.year - 1, 12, 31)


def next_reporting_window(start: dt.date | None, today: dt.date) -> str:
    """Rough Horizon periodic-reporting estimate: ~M18 then ~M36 (Phase 2)."""
    if not start:
        return ""
    for months in (18, 36, 54):
        # month arithmetic without external deps
        y, m = divmod(start.month - 1 + months, 12)
        report = start.replace(year=start.year + y, month=m + 1, day=1)
        if report >= today:
            hot = (report - today).days <= 92
            return f"~M{months} ({report:%Y-%m}){' HOT' if hot else ''}"
    return "past final report"


def score_project(row: pd.Series, today: dt.date,
                  deliverable_titles: list[str],
                  planned_digital: int, published_digital: int,
                  url_status: UrlStatus | None = None) -> ScoreBreakdown | None:
    """Full pipeline for one project. None = failed the S1 gate."""
    keywords = s1_gate(row.get("title"), row.get("objective"), deliverable_titles)
    if not keywords:
        return None
    elapsed = elapsed_fraction(row.get("start_date"), row.get("end_date"), today)
    b = ScoreBreakdown(matched_keywords=keywords)
    b.s2 = s2_timeline(elapsed)
    b.s3 = s3_absence(elapsed, row.get("url"), url_status)
    b.s4 = s4_deliverable_gap(elapsed, row.get("programme", ""),
                              planned_digital, published_digital)
    b.modifiers = modifiers(row.get("n_partners"), row.get("coordinator_activity_type"))
    b.fit = (row.get("coordinator_country") or "").strip().upper() in config.FIT_COUNTRIES
    return b


def build_prospects(con: duckdb.DuckDBPyConnection,
                    today: dt.date | None = None,
                    url_statuses: dict[str, UrlStatus] | None = None,
                    threshold: int | None = None) -> pd.DataFrame:
    """Score every in-progress project and write the prospects table."""
    today = today or dt.date.today()
    threshold = config.SCORE_THRESHOLD if threshold is None else threshold
    url_statuses = url_statuses or {}

    start_cutoff = latest_allowed_start(today) if config.REQUIRE_STARTED_BY_PREVIOUS_YEAR else today
    projects = con.execute("""
        SELECT * FROM projects
        WHERE lower(status) IN ('signed', 'active', 'ongoing')
          AND start_date IS NOT NULL AND end_date IS NOT NULL
          AND start_date <= ?
          AND end_date >= ?
    """, [start_cutoff, today]).df()
    for col in ("start_date", "end_date"):
        projects[col] = pd.to_datetime(projects[col]).dt.date
    # pandas NaN is truthy — normalize missing URLs to None for the S3 check
    projects["url"] = projects["url"].astype(object).where(projects["url"].notna(), None)

    dels = con.execute("SELECT * FROM deliverables").df()
    by_project = dict(tuple(dels.groupby("project_id"))) if len(dels) else {}

    rows = []
    for _, p in projects.iterrows():
        pid = str(p["project_id"])
        pdels = by_project.get(p["project_id"], pd.DataFrame())
        titles = pdels["title"].dropna().tolist() if len(pdels) else []
        if len(pdels):
            digital = pdels[
                pdels["deliverable_type"].fillna("").str.lower()
                    .isin(config.DIGITAL_DELIVERABLE_TYPES)
                | pdels["title"].fillna("")
                    .apply(lambda t: bool(config.LEXICON.search(t)))
            ]
            planned = len(digital)
            published = int(digital["url"].notna().sum())
        else:
            # no plan data: fall back to "strongly implied in the objective"
            planned = 1 if s1_gate(p.get("title"), p.get("objective")) else 0
            published = 0

        b = score_project(p, today, titles, planned, published,
                          url_statuses.get(pid))
        if b is None or b.total < threshold:
            continue

        start, end = p["start_date"], p["end_date"]
        start = start.date() if hasattr(start, "date") else start
        end = end.date() if hasattr(end, "date") else end
        elapsed = elapsed_fraction(start, end, today)
        us = url_statuses.get(pid)
        rows.append({
            "project_id": pid,
            "acronym": p["acronym"],
            "title": p["title"],
            "programme": p["programme"],
            "coordinator_name": p["coordinator_name"],
            "coordinator_country": p["coordinator_country"],
            "start_date": start,
            "end_date": end,
            "pct_elapsed": round(elapsed * 100, 1) if elapsed is not None else None,
            "total_cost": p["total_cost"],
            "matched_keywords": "|".join(b.matched_keywords),
            "distress_score": b.total,
            "s2_timeline": b.s2,
            "s3_absence": b.s3,
            "s4_deliverable_gap": b.s4,
            "modifiers": b.modifiers,
            "fit": b.fit,
            "priority": b.priority,
            "url": p["url"],
            "url_status": us.state if us else ("unchecked" if p["url"] else "no_url"),
            "source_link": p["source_link"],
            "next_reporting_window": next_reporting_window(start, today),
        })

    prospects = pd.DataFrame(rows)
    if len(prospects):
        prospects = prospects.sort_values(
            ["priority", "distress_score", "total_cost"],
            ascending=[False, False, False],
        ).reset_index(drop=True)

    con.execute("DROP TABLE IF EXISTS prospects")
    if len(prospects):
        con.register("prospects_df", prospects)
        con.execute("CREATE TABLE prospects AS SELECT * FROM prospects_df")
        con.unregister("prospects_df")
    log.info("prospects: %d scored above threshold %d", len(prospects), threshold)
    return prospects
