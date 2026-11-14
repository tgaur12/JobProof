"""Refresh known shortener hostnames from an HTTPS catalog and cache them."""

import argparse
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import urlsplit

import requests

if __package__:
    from .domain_checker import EXTRACT_DOMAIN, normalize_hostname
else:
    from domain_checker import EXTRACT_DOMAIN, normalize_hostname


DEFAULT_SOURCE_URL = (
    "https://raw.githubusercontent.com/MISP/misp-warninglists/main/lists/url-shortener/list.json"
)
DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[1] / ".jobproof-cache" / "shorteners.json"


def _parse_domains(values) -> frozenset[str]:
    """Validate the feed before publishing it as a complete catalog."""
    if not isinstance(values, list) or not values:
        raise ValueError("The shortener catalog must contain a nonempty domain list.")
    domains = set()
    for value in values:
        hostname, is_ip = normalize_hostname(value)
        parts = EXTRACT_DOMAIN(hostname)
        if is_ip or not parts.suffix or (not parts.domain and not parts.is_private):
            raise ValueError("Catalog entries must be hostnames, including any service subdomain.")
        domains.add(hostname)
    return frozenset(domains)


class ShortenerCatalog:
    """Load lazily, reuse fresh data, and retain good data after failed updates."""

    def __init__(self, source_url=None, cache_path=None, ttl_seconds=86400, retry_seconds=300):
        if source_url is None:
            source_url = os.environ.get("JOBPROOF_SHORTENER_FEED_URL", DEFAULT_SOURCE_URL)
        parsed = urlsplit(source_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None:
            raise ValueError("The shortener catalog source must be an HTTPS URL without credentials.")
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("The catalog lifetime must be a positive number of seconds.")
        if not math.isfinite(retry_seconds) or retry_seconds < 0:
            raise ValueError("The catalog retry interval must be zero or more seconds.")
        if cache_path is None:
            cache_path = os.environ.get("JOBPROOF_SHORTENER_CACHE", DEFAULT_CACHE_PATH)

        self.source_url = source_url
        self.cache_path = Path(cache_path)
        self.ttl_seconds = ttl_seconds
        self.retry_seconds = retry_seconds
        self._domains = None
        self._fetched_at = None
        self._last_attempt = float("-inf")
        self._error = None
        self._cache_loaded = False
        self._lock = threading.Lock()

    def _load_cache(self, now):
        try:
            cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if cached["source_url"] != self.source_url:
                return
            fetched_at = cached["fetched_at"]
            if (
                isinstance(fetched_at, bool) or not isinstance(fetched_at, (int, float))
                or not math.isfinite(fetched_at) or not 0 < fetched_at <= now
            ):
                return
            domains = _parse_domains(cached["domains"])
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            return
        self._domains = domains
        self._fetched_at = fetched_at

    def _write_cache(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.cache_path.parent,
                prefix=".shorteners-", suffix=".tmp", delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump({
                    "source_url": self.source_url,
                    "fetched_at": self._fetched_at,
                    "domains": sorted(self._domains),
                }, handle)
            os.replace(temporary_path, self.cache_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _snapshot(self, force_refresh):
        with self._lock:
            now = time.time()
            if not self._cache_loaded:
                self._load_cache(now)
                self._cache_loaded = True

            expired = self._fetched_at is None or not 0 <= now - self._fetched_at < self.ttl_seconds
            retry_due = now - self._last_attempt >= self.retry_seconds
            if force_refresh or (expired and retry_due):
                self._last_attempt = now
                try:
                    response = requests.get(self.source_url, timeout=(3, 5), allow_redirects=False)
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise ValueError("The shortener catalog source must return HTTP 200.")
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("The catalog must be a JSON object with a 'list' array.")
                    domains = _parse_domains(payload.get("list"))
                except (requests.RequestException, ValueError) as error:
                    self._error = f"Catalog refresh failed: {error}"
                else:
                    self._domains = domains
                    self._fetched_at = time.time()
                    self._error = None
                    try:
                        self._write_cache()
                    except OSError as error:
                        self._error = f"Catalog downloaded, but disk caching failed: {error}"

            status = "unavailable"
            if self._domains is not None:
                status = "stale"
                if 0 <= time.time() - self._fetched_at < self.ttl_seconds:
                    status = "fresh"
            return self._domains, {
                "status": status,
                "source_url": self.source_url,
                "fetched_at": self._fetched_at,
                "error": self._error,
            }

    def check(self, hostname, *, force_refresh=False):
        """Match a hostname against catalog entries at DNS label boundaries."""
        hostname, is_ip = normalize_hostname(hostname)
        if is_ip:
            return {
                "is_shortener": False, "matched_domain": None, "status": "not_applicable",
                "source_url": self.source_url, "fetched_at": None, "error": None,
            }

        domains, metadata = self._snapshot(force_refresh)
        matched_domain = None
        if domains is not None:
            labels = hostname.split(".")
            for index in range(len(labels)):
                candidate = ".".join(labels[index:])
                if candidate in domains:
                    matched_domain = candidate
                    break

        is_shortener = None
        if matched_domain is not None:
            is_shortener = True
        elif metadata["status"] == "fresh":
            is_shortener = False
        return {"is_shortener": is_shortener, "matched_domain": matched_domain, **metadata}


# Construction reads configuration only. The first check loads or refreshes data.
DEFAULT_CATALOG = ShortenerCatalog()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hostname", nargs="?", default="example.com", help="The hostname to check.")
    parser.add_argument("--refresh", action="store_true", help="Refresh even when cached data is fresh.")
    args = parser.parse_args()
    print(json.dumps(DEFAULT_CATALOG.check(args.hostname, force_refresh=args.refresh), indent=2))
