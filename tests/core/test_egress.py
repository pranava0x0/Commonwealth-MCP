"""Every egress rule has its known-bad refusal (../../design/architecture.md decision 0014 § 1: an
egress rule without its refusal test is prose, not policy)."""
import pytest

from commonwealth.core.egress import EgressPolicy, hosts_from_url
from commonwealth.core.errors import EgressRefused

FAIRFAX = frozenset({"www.fairfaxcounty.gov"})


def _public_resolver(host, _port):
    return [(2, 1, 6, "", ("93.184.216.34", 0))]


def _private_resolver(host, _port):
    return [(2, 1, 6, "", ("10.0.0.5", 0))]


def _policy(**kw) -> EgressPolicy:
    kw.setdefault("allowed_hosts", FAIRFAX)
    kw.setdefault("resolver", _public_resolver)
    return EgressPolicy(**kw)


def test_happy_path_passes():
    _policy().validate_url("https://www.fairfaxcounty.gov/x/query")


def test_plain_http_refused_without_manifest_flag():
    with pytest.raises(EgressRefused, match="insecure_transport"):
        _policy().validate_url("http://www.fairfaxcounty.gov/x")


def test_plain_http_allowed_with_flag_and_warned_elsewhere():
    _policy(insecure_transport=True).validate_url(
        "http://www.fairfaxcounty.gov/x")


def test_non_http_scheme_refused():
    with pytest.raises(EgressRefused, match="scheme"):
        _policy().validate_url("ftp://www.fairfaxcounty.gov/x")


def test_ip_literal_refused():
    with pytest.raises(EgressRefused, match="IP-literal"):
        EgressPolicy(allowed_hosts=frozenset({"93.184.216.34"}),
                     resolver=_public_resolver).validate_url(
            "https://93.184.216.34/x")


def test_off_registry_host_refused():
    with pytest.raises(EgressRefused, match="registered host set"):
        _policy().validate_url("https://evil.example.com/x")


def test_nonstandard_port_refused():
    with pytest.raises(EgressRefused, match="port"):
        _policy().validate_url("https://www.fairfaxcounty.gov:8443/x")


@pytest.mark.parametrize("addr,label", [
    ("127.0.0.1", "loopback"),
    ("10.1.2.3", "private"),
    ("192.168.1.1", "private"),
    ("169.254.169.254", "link-local"),   # cloud metadata
    ("100.64.0.1", "CGNAT"),
    ("::1", "loopback v6"),
    ("fc00::1", "ULA v6"),
])
def test_dns_to_blocked_range_refused(addr, label):
    def resolver(host, _port):
        return [(2, 1, 6, "", (addr, 0))]
    with pytest.raises(EgressRefused, match="resolves to"):
        _policy(resolver=resolver).validate_url(
            "https://www.fairfaxcounty.gov/x")


def test_dns_failure_refused_loudly():
    def resolver(host, _port):
        raise OSError("nxdomain")
    with pytest.raises(EgressRefused, match="DNS resolution failed"):
        _policy(resolver=resolver).validate_url(
            "https://www.fairfaxcounty.gov/x")


def test_redirect_cross_host_refused():
    with pytest.raises(EgressRefused, match="registered host set"):
        _policy().validate_redirect(
            "https://www.fairfaxcounty.gov/a", "https://evil.example.com/b", 1)


def test_redirect_hop_cap_refused():
    with pytest.raises(EgressRefused, match="redirect chain"):
        _policy().validate_redirect(
            "https://www.fairfaxcounty.gov/a", "/b", 4)


def test_redirect_same_host_relative_ok():
    target = _policy().validate_redirect(
        "https://www.fairfaxcounty.gov/a", "/b", 1)
    assert target == "https://www.fairfaxcounty.gov/b"


def test_hosts_from_url():
    assert hosts_from_url("https://Www.FairfaxCounty.gov/x") == FAIRFAX
    with pytest.raises(ValueError):
        hosts_from_url("not-a-url")


# Calls that put bytes on the wire. A `headers=` on any of these is an
# outbound header; a `headers=` anywhere else (reading a response's own
# headers, for instance) is not.
_OUTBOUND = {"AsyncClient", "Client", "build_request", "request", "send",
             "get", "post", "stream"}


def test_no_default_credential_headers_exist():
    """Cross-host credential stripping is satisfied by construction in V1:
    the fetcher sends no auth headers at all. Pin that fact.

    This used to grep the source for the string "headers=", which fired the
    moment the fetcher stored a *response's* headers in a record. Walk the
    AST and look only at outbound calls, so the test tracks the rule rather
    than one spelling of it.
    """
    import ast
    import inspect
    from commonwealth.adapters import base

    src = inspect.getsource(base.HttpFetcher)
    assert "Authorization" not in src, "HttpFetcher names an auth header"

    offenders = []
    for node in ast.walk(ast.parse(inspect.cleandoc(src))):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = (fn.attr if isinstance(fn, ast.Attribute)
                else fn.id if isinstance(fn, ast.Name) else "")
        if name not in _OUTBOUND:
            continue
        offenders += [f"{name}(headers=...)" for kw in node.keywords
                      if kw.arg in ("headers", "auth", "cookies")]
    assert offenders == [], (
        f"HttpFetcher grew outbound headers ({offenders}); implement "
        "redirect credential-stripping and replace this pin with real "
        "strip tests")


# --------------------------------------------------------------------------
# Rules 6 and 7 (GitHub issue #15). Decision 0014 froze seven rules and said
# each would get a known-bad request that must be refused. Rules 1-5 had
# theirs; 6 and 7 shipped as prose.
#
# These drive the real fetcher through httpx.MockTransport, so they exercise
# the streaming read rather than a stand-in for it.
# --------------------------------------------------------------------------
import gzip
from pathlib import Path

import httpx

from commonwealth.adapters.base import (PER_HOST_CONCURRENCY, RETRY_BUDGET,
                                        HttpFetcher)
from commonwealth.core.egress import (MAX_DECOMPRESSION_RATIO,
                                      MAX_RESPONSE_BYTES)
from commonwealth.core.errors import RateLimited, SourceUnavailable

URL = "https://www.fairfaxcounty.gov/x"


def _fetcher_over(handler, monkeypatch) -> HttpFetcher:
    """An HttpFetcher whose transport is a mock, with DNS stubbed public."""
    monkeypatch.setattr("socket.getaddrinfo", _public_resolver)
    real_client = httpx.AsyncClient

    def _client(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real_client(*a, **kw)

    monkeypatch.setattr("commonwealth.adapters.base.httpx.AsyncClient",
                        _client)
    return HttpFetcher(policy=_policy())


async def test_rule6_oversized_response_is_refused(monkeypatch):
    """A body past the cap stops the transfer rather than being downloaded
    in full and rejected afterwards."""
    huge = b'{"x":"' + b"a" * (MAX_RESPONSE_BYTES + 1024) + b'"}'
    fetcher = _fetcher_over(
        lambda req: httpx.Response(200, content=huge), monkeypatch)
    with pytest.raises(SourceUnavailable, match="egress cap"):
        await fetcher.fetch_json(URL, {})


async def test_rule6_decompression_bomb_is_refused(monkeypatch):
    """Small on the wire, large once decoded. The byte cap alone does not
    catch this: the compressed transfer is a few kilobytes."""
    payload = b'{"x":"' + b"a" * 4_000_000 + b'"}'
    packed = gzip.compress(payload)
    assert len(packed) * MAX_DECOMPRESSION_RATIO < len(payload), (
        "fixture no longer compresses hard enough to trip the ratio")

    def handler(request):
        return httpx.Response(200, content=packed,
                              headers={"content-encoding": "gzip"})

    fetcher = _fetcher_over(handler, monkeypatch)
    with pytest.raises(SourceUnavailable, match="decompression"):
        await fetcher.fetch_json(URL, {})


@pytest.mark.parametrize("fixture", sorted(
    (Path(__file__).resolve().parents[1] / "fixtures" / "sources")
    .rglob("recorded.json")), ids=lambda p: p.parent.name)
async def test_real_government_payloads_survive_the_ratio_guard(
        fixture, monkeypatch):
    """The guard must not refuse gzip in general.

    Driven from the actual recorded responses rather than a synthetic
    fixture: a made-up payload of repeated substrings compresses ~235x and
    proves nothing about real data. These five range 4.6x to 18.1x, which
    is the headroom the 50x limit was set against. If a future source
    compresses harder than the limit, this test is where that shows up.
    """
    payload = fixture.read_bytes()
    packed = gzip.compress(payload)
    ratio = len(payload) / len(packed)
    assert ratio < MAX_DECOMPRESSION_RATIO, (
        f"{fixture.parent.name} compresses {ratio:.0f}x, at or over the "
        f"{MAX_DECOMPRESSION_RATIO}x limit; re-examine the limit")

    def handler(request):
        return httpx.Response(200, content=packed,
                              headers={"content-encoding": "gzip"})

    fetcher = _fetcher_over(handler, monkeypatch)
    assert await fetcher.fetch_json(URL, {})


async def test_rule7_retry_budget_is_bounded(monkeypatch):
    """A failing host is retried RETRY_BUDGET times and then reported as an
    outage. Without a bound, one bad source stalls every caller."""
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    fetcher = _fetcher_over(handler, monkeypatch)
    monkeypatch.setattr("commonwealth.adapters.base.asyncio.sleep",
                        _no_sleep)
    with pytest.raises(SourceUnavailable, match="Outage"):
        await fetcher.fetch_json(URL, {})
    assert len(calls) == RETRY_BUDGET + 1, calls


async def test_rule7_rate_limit_is_not_retried_past_the_budget(monkeypatch):
    """429 is the publisher asking for less traffic. Answering it with
    unlimited retries is the opposite of a politeness budget."""
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "30"})

    fetcher = _fetcher_over(handler, monkeypatch)
    monkeypatch.setattr("commonwealth.adapters.base.asyncio.sleep", _no_sleep)
    with pytest.raises(RateLimited) as caught:
        await fetcher.fetch_json(URL, {})
    assert len(calls) == RETRY_BUDGET + 1, calls
    assert caught.value.retry_after_seconds == 30


async def test_rule7_per_host_concurrency_is_capped(monkeypatch):
    """No more than PER_HOST_CONCURRENCY requests are in flight to one host
    at a time, however many callers ask at once."""
    import asyncio

    live = 0
    peak = 0

    async def handler(request):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0)
        live -= 1
        return httpx.Response(200, json={"ok": True})

    fetcher = _fetcher_over(handler, monkeypatch)
    await asyncio.gather(*(fetcher.fetch_json(URL, {}) for _ in range(8)))
    assert peak <= PER_HOST_CONCURRENCY, f"peak in-flight was {peak}"


async def _no_sleep(_seconds):
    return None
