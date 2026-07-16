"""Central configuration: data sources, lexicon, scoring weights, fit countries.

Everything tunable lives here so calibration (PRD §10.3) is a one-file edit.
"""
from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
OUT_DIR = DATA_DIR / "out"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "wp4.db"

# ---------------------------------------------------------------------------
# Data sources (CORDIS bulk downloads, CC-BY — attribution required if
# outputs are ever published; see README)
# ---------------------------------------------------------------------------
CORDIS_SOURCES = {
    # dataset key -> (url, expected member csv name inside the zip)
    "horizon_projects": (
        "https://cordis.europa.eu/data/cordis-HORIZONprojects-csv.zip",
        "project.csv",
    ),
    "horizon_organizations": (
        "https://cordis.europa.eu/data/cordis-HORIZONprojects-csv.zip",
        "organization.csv",
    ),
    "horizon_deliverables": (
        "https://cordis.europa.eu/data/cordis-HORIZONprojectDeliverables-csv.zip",
        "projectDeliverables.csv",
    ),
}

# Erasmus+ / Creative Europe project lists (Phase 1) are downloaded manually
# from the Project Results Platform "Projects lists for download" page and
# dropped into data/raw/YYYY-MM/erasmus/ as CSV/XLSX. See README.
ERASMUS_SUBDIR = "erasmus"

# ---------------------------------------------------------------------------
# S1 — digital-deliverable lexicon (gate). Multilingual variants: Phase 2.
#
# Calibrated on the real 2026-06 CORDIS corpus: bare "platform" and
# "application(s)" overwhelmingly mean technology platforms and use cases in
# objective text, so they only count as WEAK signals. The gate passes on one
# STRONG match, or two distinct WEAK matches.
# ---------------------------------------------------------------------------
LEXICON_STRONG = re.compile(
    r"\b("
    r"e-?learning|mooc|gamif\w*|serious game|online course|web-?based|"
    r"(?:digital|online|interactive|web|e-) ?platform|portal|dashboard|"
    r"tool ?kit|repositor\w*|digital archive|virtual reality|"
    r"augmented reality|(?-i:VR|AR)|virtual museum|virtual tour|"
    r"(?:mobile|web|software|smartphone|digital|online) "
    r"app(?:lication)?s?|online tool|digital tool|interactive map\w*"
    r")\b",
    re.IGNORECASE,
)
LEXICON_WEAK = re.compile(
    r"\b(platform|app|apps|application|applications|interactiv\w*|"
    r"virtual|database|digital)\b",
    re.IGNORECASE,
)
# combined pattern, used for page-content checks (S3) and deliverable titles
LEXICON = re.compile(
    f"(?:{LEXICON_STRONG.pattern})|(?:{LEXICON_WEAK.pattern})",
    re.IGNORECASE,
)

# Deliverable types in CORDIS that count as digital for S4
DIGITAL_DELIVERABLE_TYPES = {
    "websites, patent fillings, videos etc.",
    "demonstrators, pilots, prototypes",
    "open research data pilot",
}

# ---------------------------------------------------------------------------
# S2 — timeline pressure bands: (lo, hi, points), evaluated in order
# ---------------------------------------------------------------------------
S2_BANDS = [
    (0.55, 0.75, 40),  # sweet spot
    (0.75, 0.90, 25),  # rescue still possible
    (0.40, 0.55, 15),  # approaching midterm
]

# ---------------------------------------------------------------------------
# S3 — absence of evidence
# ---------------------------------------------------------------------------
S3_NO_URL = 15          # no project URL at >50% elapsed
S3_URL_DEAD = 25        # URL dead / parked / placeholder
S3_URL_NO_MATCH = 10    # alive but no deliverable keywords on the page
S3_CAP = 40
S3_MIN_ELAPSED = 0.50

# URL-check heuristics
PLACEHOLDER_MAX_WORDS = 60
PARKED_MARKERS = (
    "domain is for sale", "buy this domain", "coming soon",
    "under construction", "website is parked", "account suspended",
    "index of /", "apache2 default", "welcome to nginx",
)
HTTP_TIMEOUT = 15.0
RATE_LIMIT_SECONDS = 2.0        # ≤ 1 request / 2 s (F4)
URL_CACHE_DAYS = 30
USER_AGENT = "wp4rescue/0.1 (EU open-data research; contact: uzinaduzina@gmail.com)"

# ---------------------------------------------------------------------------
# S4 — deliverable gap (Horizon only)
# ---------------------------------------------------------------------------
S4_NOTHING_PUBLISHED = 20
S4_PARTIAL = 10
S4_MIN_ELAPSED = 0.55

# ---------------------------------------------------------------------------
# Modifiers
# ---------------------------------------------------------------------------
SMALL_CONSORTIUM_MAX = 4
SMALL_CONSORTIUM_PTS = 5
NGO_COORDINATOR_PTS = 5
# CORDIS activityType: HES=university, PRC=company, REC=research org,
# PUB=public body, OTH=other (NGOs, cultural orgs, associations)
NGO_ACTIVITY_TYPES = {"OTH"}

# Fit flag: coordinator country within language/network reach.
# Tracked separately from distress (PRD §5), used for outreach priority.
FIT_COUNTRIES = {"RO", "HU", "IT", "HR", "CY", "PL", "ES", "UA"}
FIT_PTS = 5  # applied to outreach priority only, never to distress score

# Minimum distress score to appear in prospects.csv.
# Calibrated on the 2026-06 CORDIS corpus: 50 yields ~190 prospects
# (~40 fit, ~20 hot) — inside the PRD's reviewable 50-200 band.
SCORE_THRESHOLD = 50

# Eligibility: only ongoing projects that started no later than Dec 31 of the
# previous year — a project started this year cannot be in distress yet.
REQUIRE_STARTED_BY_PREVIOUS_YEAR = True

# Exclude funding schemes that never have a consortium digital deliverable to
# rescue: ERC (single-beneficiary frontier research — "platform"/"toolkit" is
# a lab method) and MSCA (fellowships/mobility). The review ritual on the first
# real run showed these were 35% of prospects and 56% of the top 50, all noise.
EXCLUDE_FUNDING_SCHEME_SUBSTRINGS = ("ERC", "MSCA")
