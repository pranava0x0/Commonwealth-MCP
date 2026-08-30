"""Adapter plumbing: egress-checked fetching, TTL cache, politeness.

Rules from design/adapters.md § 1: read-only by construction (this module has
no write verbs to call), typed errors at the boundary, TTL caching keyed by
(source, request), per-host politeness budgets, and the egress policy as the
only outbound path. The `Fetcher` seam exists so tests replay recorded
fixtures instead of hand-written shapes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from ..core.egress import (DECOMPRESSION_RATIO_FLOOR_BYTES,
                          MAX_DECOMPRESSION_RATIO, MAX_RESPONSE_BYTES,
                          EgressPolicy)
from ..core.envelope import utc_now_iso
from ..core.errors import RateLimited, SourceUnavailable
from ..core.registry import DataClassification, SourceManifest

log = logging.getLogger("commonwealth.adapters")

PER_HOST_CONCURRENCY = 2
RETRY_BUDGET = 1  # one retry inside the request deadline (../../../design/architecture.md § 38)
REQUEST_TIMEOUT_SECONDS = 30.0

_host_semaphores: dict[str, asyncio.Semaphore] = {}


def _semaphore_for(host: str) -> asyncio.Semaphore:
    if host not in _host_semaphores:
        _host_semaphores[host] = asyncio.Semaphore(PER_HOST_CONCURRENCY)
    return _host_semaphores[host]


def _declared_length(response: httpx.Response) -> int:
    """Content-Length, or 0 when absent or unparseable.

    Read once per response rather than once per chunk: it is fixed before
    the first byte arrives, and re-parsing it thousands of times down a
    20 MB stream buys nothing.
    """
    declared = response.headers.get("content-length")
    return int(declared) if declared and declared.isdigit() else 0


@dataclass
class _Body:
    """What survives a capped read.

    The httpx Response is closed as soon as the body is read, so nothing
    downstream may hold one: a streamed response that has been closed
    raises on `.content`. This carries the four things callers actually
    use.
    """
    status_code: int
    headers: httpx.Headers
    content: bytes
    url: str
    encoding: str | None


class Fetcher(Protocol):
    async def fetch_json(self, url: str, params: dict[str, Any]) -> dict: ...


class HtmlFetcher(Protocol):
    async def fetch_html(self, url: str) -> tuple[str, str]: ...


@dataclass
class HttpFetcher:
    """The only network path. Redirects are followed manually so every hop
    passes the egress policy; auth headers are never sent in V1, so the
    cross-host credential-stripping rule is satisfied by construction (a
    test pins that no default headers carry credentials)."""

    policy: EgressPolicy

    async def fetch_json(self, url: str, params: dict[str, Any]) -> dict:
        response, host = await self._fetch(url, params)
        return self._decode_json(response, host)

    async def fetch_html(self, url: str) -> tuple[str, str]:
        """Returns (html, final_url) — the final URL after any redirects,
        since some HTML sources (e.g. Virginia Law) signal "not found" by
        redirecting to a different page shape rather than a 404, and the
        caller needs to know which page it actually landed on."""
        response, host = await self._fetch(url, {})
        return self._decode_html(response, host), response.url

    async def _fetch(self, url: str,
                     params: dict[str, Any]) -> tuple[_Body, str]:
        current = url
        for hop in range(4):  # initial request + MAX_REDIRECTS
            self.policy.validate_url(current)
            host = urlparse(current).hostname or ""
            async with _semaphore_for(host):
                response = await self._request_with_retry(current, params)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise SourceUnavailable(
                        f"redirect from {host} without a Location header")
                current = self.policy.validate_redirect(current, location,
                                                        hop + 1)
                params = {}  # params were consumed by the first URL
                continue
            return response, host
        raise SourceUnavailable("redirect chain did not settle")

    async def _request_with_retry(self, url: str,
                                  params: dict[str, Any]) -> _Body:
        last: Exception | None = None
        for attempt in range(RETRY_BUDGET + 1):
            try:
                async with httpx.AsyncClient(
                        follow_redirects=False,
                        timeout=REQUEST_TIMEOUT_SECONDS) as client:
                    body = await self._read_capped(client, url, params)
            except httpx.HTTPError as err:
                last = err
                if attempt < RETRY_BUDGET:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise SourceUnavailable(
                    f"request to {urlparse(url).hostname} failed after "
                    f"{RETRY_BUDGET + 1} attempts "
                    f"({err.__class__.__name__}). This is an outage or "
                    "network problem, not an empty result.") from err
            if body.status_code == 429 or body.status_code >= 500:
                if attempt < RETRY_BUDGET:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                if body.status_code == 429:
                    retry_after = body.headers.get("retry-after")
                    raise RateLimited(
                        f"{urlparse(url).hostname} is rate-limiting "
                        "(HTTP 429); respect the politeness budget",
                        int(retry_after) if retry_after
                        and retry_after.isdigit() else None)
                raise SourceUnavailable(
                    f"{urlparse(url).hostname} returned HTTP "
                    f"{body.status_code} after retry. Outage, not an "
                    "empty result.")
            return body
        raise SourceUnavailable("unreachable") from last

    @staticmethod
    async def _read_capped(client: httpx.AsyncClient, url: str,
                           params: dict[str, Any]) -> _Body:
        """Stream the response, stopping as soon as it breaks a limit.

        Egress rule 6 has two halves. The byte cap used to be checked on
        `response.content`, which means the whole body was already
        downloaded and held in memory before being rejected — the check
        reported the problem after paying for it. Streaming stops the
        transfer at the limit instead.

        The second half is expansion. httpx decodes gzip transparently, so
        `num_bytes_downloaded` is the compressed size and the accumulated
        chunks are the decoded size. A response that decodes to far more
        than it transferred is refused whatever its final size, because the
        point of the attack is to be small on the wire.
        """
        host = urlparse(url).hostname or ""
        request = client.build_request("GET", url, params=params)
        response = await client.send(request, stream=True)
        chunks: list[bytes] = []
        decoded = 0
        # `num_bytes_downloaded` is the real on-the-wire measure, but only
        # network transports track it — under a mock it stays 0 — so the
        # declared length is the fallback. A server can only inflate that
        # header, which makes the expansion ratio look smaller, and the
        # byte cap still applies to the decoded size.
        declared = _declared_length(response)
        try:
            if response.status_code == 200:
                async for chunk in response.aiter_bytes():
                    decoded += len(chunk)
                    if decoded > MAX_RESPONSE_BYTES:
                        raise SourceUnavailable(
                            f"{host} response exceeded the "
                            f"{MAX_RESPONSE_BYTES}-byte egress cap; "
                            "transfer stopped")
                    raw = response.num_bytes_downloaded or declared
                    if (decoded > DECOMPRESSION_RATIO_FLOOR_BYTES and raw > 0
                            and decoded / raw > MAX_DECOMPRESSION_RATIO):
                        raise SourceUnavailable(
                            f"{host} response expanded {decoded // raw}x on "
                            f"decompression, over the "
                            f"{MAX_DECOMPRESSION_RATIO}x egress limit; "
                            "transfer stopped")
                    chunks.append(chunk)
            return _Body(status_code=response.status_code,
                         headers=response.headers,
                         content=b"".join(chunks),
                         url=str(response.url),
                         encoding=response.encoding)
        finally:
            await response.aclose()

    def _decode_json(self, body: _Body, host: str) -> dict:
        raw = self._checked_body(body, host)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as err:
            raise SourceUnavailable(
                f"{host} returned non-JSON where JSON was expected "
                "(bot challenge or outage page?)") from err
        if not isinstance(payload, dict):
            raise SourceUnavailable(f"{host} returned a non-object JSON body")
        return payload

    def _decode_html(self, body: _Body, host: str) -> str:
        raw = self._checked_body(body, host)
        return raw.decode(body.encoding or "utf-8", errors="replace")

    @staticmethod
    def _checked_body(body: _Body, host: str) -> bytes:
        """The size limits are enforced during the read, so all that is
        left here is the status check."""
        if body.status_code != 200:
            raise SourceUnavailable(
                f"{host} returned HTTP {body.status_code}")
        return body.content


@dataclass
class FetchResult:
    payload: dict
    retrieved_at: str          # when the bytes left the government server
    cache_age_seconds: int
    request_url: str
    # Explicit, not inferred from cache_age_seconds: TTLCache.get() truncates
    # elapsed time to an integer second, so a genuine cache hit occurring
    # under a second after insertion also reports age 0 — indistinguishable
    # from a fresh fetch by age alone.
    from_cache: bool = False


class TTLCache:
    """Response cache keyed by (source_id, url, params). Classification-aware:
    sensitive_public payloads are field-filtered BEFORE storage by the caller-
    supplied filter (structural minimization, ../../../design/architecture.md decision 0014 § 3)."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str, dict]] = {}

    @staticmethod
    def _key(source_id: str, url: str, params: dict[str, Any]) -> str:
        return json.dumps([source_id, url, sorted(params.items())],
                          separators=(",", ":"), default=str)

    def get(self, source_id: str, url: str, params: dict[str, Any],
            ttl_seconds: int) -> FetchResult | None:
        key = self._key(source_id, url, params)
        hit = self._store.get(key)
        if hit is None:
            return None
        stored_monotonic, retrieved_at, payload = hit
        age = int(time.monotonic() - stored_monotonic)
        if age > ttl_seconds:
            del self._store[key]
            return None
        return FetchResult(payload=payload, retrieved_at=retrieved_at,
                           cache_age_seconds=age, request_url=url,
                           from_cache=True)

    def put(self, source_id: str, url: str, params: dict[str, Any],
            payload: dict) -> FetchResult:
        retrieved_at = utc_now_iso()
        self._store[self._key(source_id, url, params)] = (
            time.monotonic(), retrieved_at, payload)
        return FetchResult(payload=payload, retrieved_at=retrieved_at,
                           cache_age_seconds=0, request_url=url,
                           from_cache=False)


_shared_cache = TTLCache()


def shared_cache() -> TTLCache:
    return _shared_cache


def log_source_call(manifest: SourceManifest, operation: str,
                    params: dict[str, Any], record_count: int | None) -> None:
    """Structural log minimization (../../../design/architecture.md decision 0014 § 3): open sources log
    params; sensitive_public sources log names only, never values."""
    if manifest.access.data_classification == DataClassification.sensitive_public:
        detail = f"params={sorted(params)}"
    else:
        detail = f"params={ {k: v for k, v in params.items() if k != 'f'} }"
    log.info("source=%s op=%s %s records=%s",
             manifest.id, operation, detail,
             record_count if record_count is not None else "-")


def egress_policy_for(manifest: SourceManifest,
                      service_url: str) -> EgressPolicy:
    host = urlparse(service_url).hostname
    if not host:
        raise ValueError(f"manifest {manifest.id}: service_url has no host")
    return EgressPolicy(
        allowed_hosts=frozenset({host.lower()}),
        insecure_transport=manifest.access.insecure_transport)
