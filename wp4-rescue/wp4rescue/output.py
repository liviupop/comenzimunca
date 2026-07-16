"""F5 — Output: ranked prospects.csv + monthly diff report."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from . import config

log = logging.getLogger(__name__)

PIPELINE_STATUSES = ["new", "researched", "contacted", "replied",
                     "meeting", "won", "lost"]


def write_prospects(prospects: pd.DataFrame, month: str) -> Path:
    """Write data/out/prospects-YYYY-MM.csv, preserving pipeline status (F6)
    for prospects already present in the previous run."""
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.OUT_DIR / f"prospects-{month}.csv"

    prospects = prospects.copy()
    prospects["pipeline_status"] = "new"
    prev = _latest_before(month)
    if prev is not None:
        old = pd.read_csv(prev, dtype={"project_id": str})
        if "pipeline_status" in old.columns:
            carried = old.set_index("project_id")["pipeline_status"].to_dict()
            prospects["pipeline_status"] = [
                carried.get(pid, "new") for pid in prospects["project_id"].astype(str)
            ]

    prospects.to_csv(path, index=False)
    # stable symlink-style copy for `make refresh` consumers
    prospects.to_csv(config.OUT_DIR / "prospects.csv", index=False)
    log.info("wrote %s (%d prospects)", path, len(prospects))
    return path


def _latest_before(month: str) -> Path | None:
    candidates = sorted(
        p for p in config.OUT_DIR.glob("prospects-????-??.csv")
        if p.stem.removeprefix("prospects-") < month
    )
    return candidates[-1] if candidates else None


def write_diff(month: str) -> Path | None:
    """Monthly diff: new prospects + score increases vs. the previous run."""
    current_path = config.OUT_DIR / f"prospects-{month}.csv"
    prev_path = _latest_before(month)
    if prev_path is None or not current_path.exists():
        log.info("no previous month to diff against")
        return None

    cur = pd.read_csv(current_path, dtype={"project_id": str})
    old = pd.read_csv(prev_path, dtype={"project_id": str})
    old_scores = old.set_index("project_id")["distress_score"].to_dict()

    new_rows = cur[~cur["project_id"].isin(old_scores)]
    increased = cur[[pid in old_scores and s > old_scores[pid]
                     for pid, s in zip(cur["project_id"], cur["distress_score"])]]

    lines = [f"# wp4.rescue diff — {month} vs {prev_path.stem.removeprefix('prospects-')}",
             "", f"## New this month ({len(new_rows)})", ""]
    for _, r in new_rows.iterrows():
        lines.append(f"- [{r['distress_score']}] {r['acronym']} — {r['title']} "
                     f"({r['coordinator_country']}) {r['source_link']}")
    lines += ["", f"## Score increased ({len(increased)})", ""]
    for _, r in increased.iterrows():
        lines.append(f"- [{old_scores[r['project_id']]} → {r['distress_score']}] "
                     f"{r['acronym']} — {r['title']} {r['source_link']}")

    path = config.OUT_DIR / f"diff-{month}.md"
    path.write_text("\n".join(lines) + "\n")
    log.info("wrote %s (%d new, %d increased)", path, len(new_rows), len(increased))
    return path
