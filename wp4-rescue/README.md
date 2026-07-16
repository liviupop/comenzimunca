# wp4.rescue — EU Project Distress Detector

A prospecting engine that finds funded EU projects likely to be struggling
with their digital deliverables, from official open data. Every consortium
veteran knows the platform always lives in Work Package 4.

Phase 0 MVP per the PRD: Horizon Europe ingest → S1 digital-promise gate →
S2 timeline + S4 deliverable-gap scoring → ranked `prospects.csv`. S3 URL
liveness enrichment (Phase 2) is already implemented behind `--enrich`.

## Quick start

```bash
make install     # pip install requirements (Python 3.11+)
make demo        # end-to-end run on bundled synthetic data, no network
make test        # unit tests for the scoring model
```

Real run (downloads ~hundreds of MB of CORDIS bulk CSVs on first use):

```bash
make refresh     # ingest + score for the current month
make enrich      # same, plus polite URL liveness checks (S3) — slow by design
```

> **Run `make enrich` from an open network**, not a restricted CI/sandbox.
> Behind a filtering proxy, external sites return 403 and would be misread as
> "dead". The checker treats 401/403/405/429/451 and proxy errors as *blocked*
> (neutral, not distress evidence), but a sandbox that blocks everything yields
> no useful S3 signal — run it locally.

Outputs land in `data/out/`:

- `prospects-YYYY-MM.csv` — ranked prospects (also copied to `prospects.csv`)
- `diff-YYYY-MM.md` — new prospects and score increases vs. the previous month

Monthly automation: `crontab -e` →
`0 6 3 * * cd /path/to/wp4-rescue && make refresh`

## The Distress Score (0–100)

| Signal | Points | What it measures |
|---|---|---|
| **S1** digital promise | gate | objective/deliverable titles match the digital lexicon (platform, portal, app, e-learning, gamif\*, VR…) |
| **S2** timeline pressure | 0–40 | 0.55–0.75 elapsed = 40 (the sweet spot), 0.75–0.9 = 25, 0.4–0.55 = 15 |
| **S3** absence of evidence | 0–40 | no URL at >50% elapsed +15; URL dead/parked +25; alive but no deliverable keywords +10 (capped at 40) |
| **S4** deliverable gap | 0–20 | Horizon only: digital deliverables planned, nothing published at >55% elapsed +20; partial +10 |
| Modifiers | +0–10 | ≤4 partners +5; coordinator is `OTH` (NGO/cultural) +5 |

A separate **Fit** flag (coordinator in RO/HU/IT/HR/CY/PL/ES/UA) adds +5 to
the *outreach priority* ordering but never enters the distress score itself.

**Eligibility (before any scoring):**
- only *ongoing* projects — status SIGNED/active, not yet ended — that
  **started no later than Dec 31 of the previous year** (a project started
  this year cannot be in distress yet; toggle
  `REQUIRE_STARTED_BY_PREVIOUS_YEAR`).
- **ERC and MSCA schemes excluded.** The first real run's review ritual showed
  these single-beneficiary frontier-research / fellowship grants were 35% of
  prospects and 56% of the top 50 — all noise, because "platform"/"toolkit"
  there means a lab method, not a consortium deliverable to rescue (toggle
  `EXCLUDE_FUNDING_SCHEME_SUBSTRINGS`).

**S1 lexicon is two-tier** (calibrated on real 2026-06 CORDIS text): bare
`platform`/`application(s)` are *weak* signals (they usually mean a technology
platform or a use case), so the gate needs one *strong* match (e-learning,
portal, dashboard, "mobile app", gamif*, VR/AR, …) or two distinct weak ones.

All thresholds live in `wp4rescue/config.py`. Default output cutoff is 40 —
tune it after the first run to get a reviewable ~50/month (PRD §10.3).

## Layout

```
wp4rescue/
  config.py     lexicon, weights, bands, fit countries, source URLs
  ingest.py     F1: download + cache CORDIS zips into data/raw/YYYY-MM/
  normalize.py  F2: DuckDB unified projects + deliverables tables
  score.py      F3: S1 gate, S2–S4, modifiers, prospects table
  enrich.py     F4: URL liveness (robots.txt, 1 req/2s, 30-day cache)
  output.py     F5/F6: ranked CSV, monthly diff, pipeline-status carry-over
  cli.py        ingest / score / refresh / demo
sample_data/    synthetic CORDIS-format CSVs for the demo & smoke tests
```

## Dashboard (Cloudflare Pages)

`site/` is a **static viewer app with zero data in it** — this repo is public,
so prospect data never touches git. You drag-and-drop your locally generated
`prospects.csv` into the page; data stays in your browser (localStorage).
Pipeline-status edits made in the dashboard are saved locally and come back
out via *Export CSV* — feed that file to the next `make refresh` cycle.

Deploy (Cloudflare Pages ↔ GitHub, no build step):

1. Cloudflare dashboard → **Workers & Pages → Create → Pages → Connect to Git**
   → select `liviupop/comenzimunca`.
2. Build settings: *Framework preset* **None**, *Build command* — leave empty,
   *Build output directory* **`wp4-rescue/site`**.
3. Recommended: **Zero Trust → Access → Applications → Add an application →
   Self-hosted**, domain = your `*.pages.dev` host, policy = *Allow* your
   email (One-time PIN). Free for up to 50 users. The page also ships
   `noindex` headers and meta, but Access is the real lock.

Every push to the default branch redeploys the viewer. Since the data lives
only in your browser, redeploys never touch it.

## Pipeline tracking (F6)

`prospects-*.csv` has a `pipeline_status` column
(`new → researched → contacted → replied → meeting → won/lost`). Edit it in
the CSV; the next monthly run carries your statuses forward by project id.

## Ground rules

- **Local-first, €0.** All data open (CC-BY), all compute local. Attribute
  data.europa.eu / CORDIS if outputs are ever published.
- **Compliance.** Only organization-level public data is stored. Personal
  contact discovery stays manual and outside the tool.
- **Honesty constraint (hard rule).** The tool informs *who to contact and
  when*, never the outreach text. Messages never reference the diagnosis.
  Never publish scores or name struggling projects — methodology only.
- **Polite enrichment.** ≤1 request/2s, honest User-Agent, robots.txt
  respected, results cached 30 days.

## Known limits (by design, PRD §9)

- CORDIS deliverables coverage is partial and lags reality — S4 is one
  signal among four; manual review before outreach is mandatory.
- CORDIS column names drift; `normalize.py` resolves candidates and fails
  loudly on schema changes. CSV is pinned as the interchange format.
- Erasmus+/Creative Europe (Phase 1): download the project lists from the
  Project Results Platform into `data/raw/YYYY-MM/erasmus/` — loader lands
  in Phase 1 along with the multilingual lexicon.
