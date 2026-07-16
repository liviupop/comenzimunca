"""wp4.rescue command line: ingest / score / refresh / diff.

  python -m wp4rescue refresh              # full monthly run (no URL checks)
  python -m wp4rescue refresh --enrich     # + S3 URL liveness (slow, polite)
  python -m wp4rescue score --month 2026-07 --threshold 40
  python -m wp4rescue demo                 # end-to-end run on sample_data/
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

import duckdb

from . import config, ingest, normalize, output, score

log = logging.getLogger("wp4rescue")


def _connect() -> duckdb.DuckDBPyConnection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(config.DB_PATH))


def cmd_ingest(month: str) -> dict[str, Path]:
    return ingest.ingest_month(month)


def cmd_score(month: str, threshold: int | None, enrich_urls: bool,
              raw_dir: Path | None = None) -> None:
    raw = raw_dir or ingest.month_dir(month)
    con = _connect()
    normalize.normalize(
        con,
        project_csv=raw / "project.csv",
        organization_csv=raw / "organization.csv",
        deliverables_csv=raw / "projectDeliverables.csv",
    )

    url_statuses = {}
    if enrich_urls:
        from . import enrich as enrich_mod
        # gate first (S1) so we only hit URLs of projects we actually care about
        gated = con.execute("""
            SELECT project_id, url FROM projects
            WHERE url IS NOT NULL AND lower(status) IN ('signed','active','ongoing')
        """).fetchall()
        candidates = {
            str(pid): url for pid, url in gated
            if score.s1_gate(None, con.execute(
                "SELECT title || ' ' || COALESCE(objective,'') FROM projects WHERE project_id = ?",
                [pid]).fetchone()[0])
        }
        log.info("enriching %d gated project URLs", len(candidates))
        url_statuses = enrich_mod.enrich(candidates)

    prospects = score.build_prospects(con, url_statuses=url_statuses,
                                      threshold=threshold)
    output.write_prospects(prospects, month)
    output.write_diff(month)
    con.close()

    if len(prospects):
        top = prospects.head(10)[["distress_score", "acronym",
                                  "coordinator_country", "fit"]]
        print(f"\n{len(prospects)} prospects above threshold. Top 10:\n")
        print(top.to_string(index=False))
    else:
        print("No prospects above threshold — lower it or check the data.")


def cmd_demo() -> None:
    """Run the whole pipeline against the bundled synthetic sample data."""
    sample = config.ROOT / "sample_data"
    month = dt.date.today().strftime("%Y-%m")
    cmd_score(month, threshold=1, enrich_urls=False, raw_dir=sample)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="wp4rescue",
                                     description="EU project distress detector")
    sub = parser.add_subparsers(dest="cmd", required=True)

    month_default = dt.date.today().strftime("%Y-%m")
    for name in ("ingest", "score", "refresh"):
        p = sub.add_parser(name)
        p.add_argument("--month", default=month_default,
                       help="data version, YYYY-MM (default: current month)")
        if name != "ingest":
            p.add_argument("--threshold", type=int, default=None,
                           help=f"min distress score (default {config.SCORE_THRESHOLD})")
            p.add_argument("--enrich", action="store_true",
                           help="run S3 URL liveness checks (slow, rate-limited)")
    sub.add_parser("demo")

    args = parser.parse_args(argv)
    if args.cmd == "ingest":
        cmd_ingest(args.month)
    elif args.cmd == "score":
        cmd_score(args.month, args.threshold, args.enrich)
    elif args.cmd == "refresh":
        cmd_ingest(args.month)
        cmd_score(args.month, args.threshold, args.enrich)
    elif args.cmd == "demo":
        cmd_demo()
    return 0


if __name__ == "__main__":
    sys.exit(main())
