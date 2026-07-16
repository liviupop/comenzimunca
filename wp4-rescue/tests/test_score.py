"""Unit tests for the scoring model (PRD §5)."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import duckdb

from wp4rescue import config
from wp4rescue.enrich import classify_page
from wp4rescue.score import (
    UrlStatus, build_prospects, elapsed_fraction, latest_allowed_start,
    modifiers, next_reporting_window, s1_gate, s2_timeline, s3_absence,
    s4_deliverable_gap, score_project,
)

TODAY = dt.date(2026, 7, 16)


# --- S1 gate ---------------------------------------------------------------

def test_s1_matches_digital_keywords():
    assert "platform" in s1_gate("An interactive platform", "")
    assert s1_gate("", "We build a gamified e-learning MOOC") != []
    assert s1_gate("A mobile app for farmers", None) != []


def test_s1_rejects_non_digital():
    assert s1_gate("Quantum materials synthesis", "spin transport studies") == []


def test_s1_lone_weak_keyword_fails():
    # calibrated on real CORDIS data: generic tech-speak must not pass
    assert s1_gate("", "a novel biotech platform for enzyme discovery") == []
    assert s1_gate("", "with wide industrial applications") == []
    assert s1_gate("", "applications of our catalysis platform") != []  # 2 weak


def test_s1_strong_for_s4_fallback():
    from wp4rescue.score import s1_strong
    assert s1_strong("", "an e-learning portal for teachers") is True
    assert s1_strong("", "a platform for enzyme applications") is False


def test_s1_uses_deliverable_titles():
    assert s1_gate("Generic title", "generic text", ["D4.1 Web portal"]) != []


# --- S2 timeline bands -----------------------------------------------------

@pytest.mark.parametrize("elapsed,expected", [
    (0.30, 0), (0.40, 15), (0.50, 15), (0.60, 40), (0.75, 40),
    (0.80, 25), (0.90, 25), (0.95, 0), (None, 0),
])
def test_s2_bands(elapsed, expected):
    assert s2_timeline(elapsed) == expected


def test_elapsed_fraction():
    assert elapsed_fraction(dt.date(2024, 1, 1), dt.date(2026, 1, 1),
                            dt.date(2025, 1, 1)) == pytest.approx(0.5, abs=0.01)
    assert elapsed_fraction(None, dt.date(2026, 1, 1), TODAY) is None
    assert elapsed_fraction(dt.date(2026, 1, 1), dt.date(2026, 1, 1), TODAY) is None


# --- S3 absence of evidence -------------------------------------------------

def test_s3_no_url_after_half():
    assert s3_absence(0.6, None, None) == config.S3_NO_URL
    assert s3_absence(0.4, None, None) == 0  # too early


def test_s3_dead_and_parked():
    assert s3_absence(0.6, "http://x", UrlStatus("dead")) == config.S3_URL_DEAD
    assert s3_absence(0.6, "http://x", UrlStatus("parked")) == config.S3_URL_DEAD


def test_s3_alive_variants():
    assert s3_absence(0.6, "http://x", UrlStatus("alive_no_match")) == config.S3_URL_NO_MATCH
    assert s3_absence(0.6, "http://x", UrlStatus("alive_match")) == 0
    assert s3_absence(0.6, "http://x", None) == 0  # unchecked URL scores nothing


# --- S4 deliverable gap ----------------------------------------------------

def test_s4_nothing_published():
    assert s4_deliverable_gap(0.6, "HORIZON", 3, 0) == config.S4_NOTHING_PUBLISHED


def test_s4_partial():
    assert s4_deliverable_gap(0.6, "HORIZON", 3, 1) == config.S4_PARTIAL


def test_s4_gates():
    assert s4_deliverable_gap(0.5, "HORIZON", 3, 0) == 0    # too early
    assert s4_deliverable_gap(0.6, "ERASMUS", 3, 0) == 0    # Horizon only
    assert s4_deliverable_gap(0.6, "HORIZON", 0, 0) == 0    # nothing promised
    assert s4_deliverable_gap(0.6, "HORIZON", 2, 2) == 0    # all published


# --- Modifiers & fit ---------------------------------------------------------

def test_modifiers():
    assert modifiers(3, "OTH") == 10
    assert modifiers(3, "HES") == 5
    assert modifiers(10, "OTH") == 5
    assert modifiers(10, "PRC") == 0


def test_fit_flag_not_in_distress_score():
    row = pd.Series({
        "title": "Digital platform", "objective": "an online portal",
        "start_date": dt.date(2024, 8, 1), "end_date": dt.date(2027, 7, 31),
        "url": None, "programme": "HORIZON", "n_partners": 3,
        "coordinator_activity_type": "OTH", "coordinator_country": "RO",
    })
    b = score_project(row, TODAY, [], planned_digital=2, published_digital=0)
    assert b.fit is True
    assert b.priority == b.total + config.FIT_PTS
    # distress components only: S2=40 (0.65 elapsed) + S3=15 + S4=20 + mods=10
    assert b.total == 85


def test_gate_returns_none():
    row = pd.Series({
        "title": "Quantum sensing", "objective": "materials science",
        "start_date": dt.date(2024, 1, 1), "end_date": dt.date(2027, 1, 1),
        "url": None, "programme": "HORIZON", "n_partners": 3,
        "coordinator_activity_type": "REC", "coordinator_country": "DE",
    })
    assert score_project(row, TODAY, [], 0, 0) is None


# --- Eligibility: ongoing + started by last year -----------------------------

def test_latest_allowed_start():
    assert latest_allowed_start(dt.date(2026, 7, 16)) == dt.date(2025, 12, 31)


def _project_row(pid, start, end, status="SIGNED", scheme="HORIZON-RIA"):
    return (pid, "HORIZON", f"P{pid}", "Digital platform project",
            "an interactive online portal", start, end, 100000.0, None,
            "ORG", "RO", "OTH", 3, scheme, status, "https://example.org")


def _make_con():
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE projects (
        project_id VARCHAR, programme VARCHAR, acronym VARCHAR, title VARCHAR,
        objective VARCHAR, start_date DATE, end_date DATE, total_cost DOUBLE,
        url VARCHAR, coordinator_name VARCHAR, coordinator_country VARCHAR,
        coordinator_activity_type VARCHAR, n_partners INT, funding_scheme VARCHAR,
        status VARCHAR, source_link VARCHAR)""")
    con.execute("""CREATE TABLE deliverables (
        project_id VARCHAR, title VARCHAR, deliverable_type VARCHAR, url VARCHAR)""")
    return con


def test_build_prospects_eligibility():
    con = _make_con()
    rows = [
        _project_row("1", dt.date(2024, 8, 1), dt.date(2027, 7, 31)),   # eligible
        _project_row("2", dt.date(2026, 2, 1), dt.date(2028, 1, 31)),   # started THIS year -> out
        _project_row("3", dt.date(2023, 1, 1), dt.date(2026, 1, 1)),    # already ended -> out
        _project_row("4", dt.date(2024, 8, 1), dt.date(2027, 7, 31), status="CLOSED"),  # not ongoing -> out
    ]
    con.executemany("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    prospects = build_prospects(con, today=TODAY, threshold=1)
    assert list(prospects["project_id"]) == ["1"]


def test_build_prospects_excludes_erc_msca():
    con = _make_con()
    rows = [
        _project_row("1", dt.date(2024, 8, 1), dt.date(2027, 7, 31), scheme="HORIZON-RIA"),   # in
        _project_row("2", dt.date(2024, 8, 1), dt.date(2027, 7, 31), scheme="HORIZON-ERC"),   # out
        _project_row("3", dt.date(2024, 8, 1), dt.date(2027, 7, 31), scheme="HORIZON-MSCA-PF"),  # out
        _project_row("4", dt.date(2024, 8, 1), dt.date(2027, 7, 31), scheme="HORIZON-IA"),    # in
    ]
    con.executemany("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    prospects = build_prospects(con, today=TODAY, threshold=1)
    assert set(prospects["project_id"]) == {"1", "4"}


# --- URL classification ------------------------------------------------------

def test_classify_dead():
    assert classify_page(404, "").state == "dead"


def test_classify_parked():
    assert classify_page(200, "<html>This domain is for sale</html>").state == "parked"
    assert classify_page(200, "<html><p>tiny page</p></html>").state == "parked"


def test_classify_alive():
    filler = "word " * 100
    assert classify_page(200, f"<p>{filler} our e-learning platform</p>").state == "alive_match"
    assert classify_page(200, f"<p>{filler} annual report of activities</p>").state == "alive_no_match"


# --- Reporting window --------------------------------------------------------

def test_next_reporting_window():
    # started 2025-03-01 -> M18 = 2026-09, ~2 months out from TODAY = hot
    assert "HOT" in next_reporting_window(dt.date(2025, 3, 1), TODAY)
    # started 2026-01-01 -> M18 = 2027-07, not hot
    w = next_reporting_window(dt.date(2026, 1, 1), TODAY)
    assert "M18" in w and "HOT" not in w
    assert next_reporting_window(None, TODAY) == ""
