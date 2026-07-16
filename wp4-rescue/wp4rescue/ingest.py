"""F1 — Ingest: download and cache CORDIS bulk CSVs, versioned by month.

Idempotent: a file already present under data/raw/YYYY-MM/ is never
re-downloaded. Raw zips are kept so a re-extract never needs the network.
"""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from . import config

log = logging.getLogger(__name__)


def month_dir(month: str) -> Path:
    """data/raw/YYYY-MM/ for the given month string."""
    d = config.RAW_DIR / month
    d.mkdir(parents=True, exist_ok=True)
    return d


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=30))
def _download(url: str) -> bytes:
    log.info("downloading %s", url)
    with httpx.Client(
        timeout=120.0, follow_redirects=True,
        headers={"User-Agent": config.USER_AGENT},
    ) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.content


def _extract_member(zip_bytes: bytes, member_name: str, dest: Path) -> Path:
    """Extract a single CSV from a CORDIS zip (members may sit under csv/)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        candidates = [n for n in zf.namelist() if Path(n).name == member_name]
        if not candidates:
            raise RuntimeError(
                f"schema drift: {member_name!r} not found in zip "
                f"(members: {zf.namelist()[:10]}…) — check CORDIS bundle layout"
            )
        with zf.open(candidates[0]) as src:
            dest.write_bytes(src.read())
    return dest


def ingest_month(month: str) -> dict[str, Path]:
    """Fetch every configured CORDIS source into data/raw/<month>/.

    Returns {dataset_key: extracted_csv_path}. Idempotent per file.
    """
    dest_dir = month_dir(month)
    out: dict[str, Path] = {}
    zip_cache: dict[str, bytes] = {}

    for key, (url, member) in config.CORDIS_SOURCES.items():
        csv_path = dest_dir / member
        out[key] = csv_path
        if csv_path.exists():
            log.info("cached: %s", csv_path)
            continue
        zip_path = dest_dir / Path(url).name
        if zip_path.exists():
            zip_bytes = zip_path.read_bytes()
        elif url in zip_cache:
            zip_bytes = zip_cache[url]
        else:
            zip_bytes = _download(url)
            zip_path.write_bytes(zip_bytes)
            zip_cache[url] = zip_bytes
        _extract_member(zip_bytes, member, csv_path)
        log.info("extracted %s -> %s", member, csv_path)

    return out
