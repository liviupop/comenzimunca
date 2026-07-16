"""F4 — Enrich: polite URL liveness checks for gated projects only.

Rules (PRD §6 F4 + §7 compliance):
  - ≤ 1 request / 2 s, honest User-Agent, 15 s timeout
  - robots.txt respected
  - results cached 30 days in data/cache/url_checks.json
Classification feeds S3: dead | parked | alive_no_match | alive_match.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.robotparser
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx

from . import config
from .score import UrlStatus

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.S | re.I)


def _load_cache() -> dict:
    path = config.CACHE_DIR / "url_checks.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            log.warning("corrupt url cache, starting fresh")
    return {}


def _save_cache(cache: dict) -> None:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (config.CACHE_DIR / "url_checks.json").write_text(
        json.dumps(cache, indent=1, default=str)
    )


def _robots_allowed(url: str, client: httpx.Client) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = client.get(robots_url)
        if r.status_code >= 400:
            return True  # no robots.txt -> allowed
        rp.parse(r.text.splitlines())
        return rp.can_fetch(config.USER_AGENT, url)
    except httpx.HTTPError:
        return True


def classify_page(status_code: int, html: str) -> UrlStatus:
    # bot-protection / rate-limit / auth: the site is up, we just can't see it —
    # NOT evidence the promised deliverable is missing, so treat as neutral
    if status_code in (401, 403, 405, 429, 451):
        return UrlStatus("blocked", f"HTTP {status_code} (access blocked, not dead)")
    if status_code >= 400:
        return UrlStatus("dead", f"HTTP {status_code}")
    text = _TAG_RE.sub(" ", html)
    words = text.split()
    lowered = text.lower()
    for marker in config.PARKED_MARKERS:
        if marker in lowered:
            return UrlStatus("parked", f"marker: {marker!r}")
    if len(words) < config.PLACEHOLDER_MAX_WORDS:
        return UrlStatus("parked", f"placeholder: only {len(words)} words")
    if config.LEXICON.search(text):
        return UrlStatus("alive_match", "deliverable keywords present")
    return UrlStatus("alive_no_match", "no deliverable keywords on page")


def check_url(url: str, client: httpx.Client) -> UrlStatus:
    if not _robots_allowed(url, client):
        return UrlStatus("alive_match", "robots.txt disallows — assume fine")
    try:
        r = client.get(url)
        return classify_page(r.status_code, r.text)
    except httpx.ProxyError as e:
        # network-policy artifact, not the site being down
        return UrlStatus("blocked", f"proxy: {e}")
    except httpx.HTTPError as e:
        return UrlStatus("dead", f"{type(e).__name__}")


def enrich(url_by_project: dict[str, str]) -> dict[str, UrlStatus]:
    """Check each project URL (cache-aware, rate-limited). Returns statuses."""
    cache = _load_cache()
    cutoff = datetime.now() - timedelta(days=config.URL_CACHE_DAYS)
    out: dict[str, UrlStatus] = {}

    with httpx.Client(
        timeout=config.HTTP_TIMEOUT, follow_redirects=True,
        headers={"User-Agent": config.USER_AGENT},
    ) as client:
        for pid, url in url_by_project.items():
            if not url:
                continue
            entry = cache.get(url)
            if entry and datetime.fromisoformat(entry["checked"]) > cutoff:
                out[pid] = UrlStatus(entry["state"], entry["detail"])
                continue
            status = check_url(url, client)
            out[pid] = status
            cache[url] = {
                "state": status.state, "detail": status.detail,
                "checked": datetime.now().isoformat(),
            }
            log.info("checked %s -> %s (%s)", url, status.state, status.detail)
            time.sleep(config.RATE_LIMIT_SECONDS)

    _save_cache(cache)
    return out
