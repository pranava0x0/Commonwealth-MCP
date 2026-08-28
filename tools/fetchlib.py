"""Shared HTTP helper for the research scripts.

Stdlib only. Every fetch goes through get() so retry, timeout, and
User-Agent behavior stay in one place.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

USER_AGENT = "commonwealth-mcp-research/0.1 (public-data research; contact: repo issues)"
DEFAULT_TIMEOUT = 30
RETRIES = 3
BACKOFF_SECONDS = 2.0


class FetchError(RuntimeError):
    """A fetch that failed after retries, or returned a non-2xx status."""


def get(url: str, headers: dict[str, str] | None = None,
        timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """GET a URL with retries. Raises FetchError on final failure."""
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        req = urllib.request.Request(url, headers=merged)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            # 4xx will not improve on retry; 429/5xx might.
            if err.code == 429 or err.code >= 500:
                last_err = err
                sleep = BACKOFF_SECONDS * attempt
                log.warning("HTTP %s on %s (attempt %d/%d), retrying in %.1fs",
                            err.code, url, attempt, RETRIES, sleep)
                time.sleep(sleep)
                continue
            raise FetchError(f"HTTP {err.code} on {url}") from err
        except (urllib.error.URLError, TimeoutError) as err:
            last_err = err
            sleep = BACKOFF_SECONDS * attempt
            log.warning("%s on %s (attempt %d/%d), retrying in %.1fs",
                        err, url, attempt, RETRIES, sleep)
            time.sleep(sleep)
    raise FetchError(f"failed after {RETRIES} attempts: {url}") from last_err


def get_json(url: str, headers: dict[str, str] | None = None,
             timeout: int = DEFAULT_TIMEOUT) -> Any:
    """GET a URL and parse JSON. Raises FetchError if the body is not JSON.

    A non-JSON body usually means the host served a bot-challenge page or a
    JS app shell; surfacing that beats a confusing JSONDecodeError.
    """
    body = get(url, headers=headers, timeout=timeout)
    text = body.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("<"):
        raise FetchError(
            f"{url} returned HTML, not JSON (bot challenge or app shell); "
            f"first 120 chars: {stripped[:120]!r}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        raise FetchError(f"{url} returned unparseable JSON: {err}") from err
