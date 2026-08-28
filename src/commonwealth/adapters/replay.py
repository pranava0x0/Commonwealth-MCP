"""Replay fetcher over recorded exchanges — the offline seam shared by the
test suite and the site/demo generator. Unknown requests fail loudly; a
replay that silently returned nothing would make every consumer vacuous."""
from __future__ import annotations

import copy
import json
from typing import Any


class ReplayFetcher:
    def __init__(self, exchanges: list[dict]) -> None:
        self._map: dict[str, dict] = {}
        for ex in exchanges:
            self._map[self._key(ex["url"], ex["params"])] = ex["response"]
        if not self._map:
            raise AssertionError("replay fetcher constructed with zero "
                                 "exchanges — fixture is empty or unloaded")
        self.calls: list[str] = []

    @staticmethod
    def _key(url: str, params: dict[str, Any]) -> str:
        return json.dumps(
            [url, sorted((k, str(v)) for k, v in params.items())],
            separators=(",", ":"))

    async def fetch_json(self, url: str, params: dict[str, Any]) -> dict:
        key = self._key(url, params)
        self.calls.append(key)
        if key not in self._map:
            known = "\n  ".join(sorted(self._map)[:8])
            raise AssertionError(
                f"no recorded exchange for:\n  {key}\nknown (first 8):\n  {known}")
        return copy.deepcopy(self._map[key])


class HtmlReplayFetcher:
    """Companion to ReplayFetcher for HTML-page adapters (e.g. Virginia
    Law): replays recorded (request url -> (html, final url)) pairs. No
    redirect-chain simulation needed — the recording already carries
    wherever the live fetch actually landed."""

    def __init__(self, pages: dict[str, tuple[str, str]]) -> None:
        self._pages = pages
        if not self._pages:
            raise AssertionError("html replay fetcher constructed with "
                                 "zero pages — fixture is empty or unloaded")
        self.calls: list[str] = []

    async def fetch_html(self, url: str) -> tuple[str, str]:
        self.calls.append(url)
        if url not in self._pages:
            known = "\n  ".join(sorted(self._pages))
            raise AssertionError(
                f"no recorded page for:\n  {url}\nknown:\n  {known}")
        return self._pages[url]
