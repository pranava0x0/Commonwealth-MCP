"""Every egress rule has its known-bad refusal (../../design/architecture.md decision 0014 § 1: an
egress rule without its refusal test is prose, not policy)."""
import pytest

from commonwealth.core.egress import (DENY_NETWORK_ENV, EgressPolicy,
                                      hosts_from_url, network_denied)
from commonwealth.core.errors import EgressRefused

FAIRFAX = frozenset({"www.fairfaxcounty.gov"})


@pytest.fixture(autouse=True)
def _switch_off(monkeypatch):
    """Every rule below is about a URL the policy judges on its merits, so
    the deny switch has to be off for all of them — including on a machine
    or a CI job that exported it for the whole suite."""
    monkeypatch.delenv(DENY_NETWORK_ENV, raising=False)


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


@pytest.mark.parametrize("value", ["1", "true", "yes", "anything"])
def test_deny_switch_refuses_every_host(monkeypatch, value):
    """Rule 8. The switch is checked before the scheme, the allowlist and
    DNS, so a URL that would otherwise sail through is still refused."""
    monkeypatch.setenv(DENY_NETWORK_ENV, value)
    with pytest.raises(EgressRefused, match=DENY_NETWORK_ENV):
        _policy().validate_url("https://www.fairfaxcounty.gov/x/query")


def test_deny_switch_refuses_before_dns_is_resolved(monkeypatch):
    """The point of the switch is that nothing leaves the process, and a
    DNS lookup leaves the process. A resolver that fails the test if it is
    called at all pins that."""
    def _explode(host, _port):
        raise AssertionError(f"the resolver was called for {host!r}")

    monkeypatch.setenv(DENY_NETWORK_ENV, "1")
    with pytest.raises(EgressRefused):
        _policy(resolver=_explode).validate_url(
            "https://www.fairfaxcounty.gov/x")


def test_deny_switch_also_refuses_redirect_targets(monkeypatch):
    """Redirects re-enter validate_url, so they inherit the refusal rather
    than needing their own check."""
    monkeypatch.setenv(DENY_NETWORK_ENV, "1")
    with pytest.raises(EgressRefused, match=DENY_NETWORK_ENV):
        _policy().validate_redirect("https://www.fairfaxcounty.gov/a",
                                    "/b", 1)


@pytest.mark.parametrize("value", ["", "0", "   "])
def test_the_off_values_leave_the_policy_alone(monkeypatch, value):
    """An empty variable is the shape a shell exports by accident, and it
    must not switch the network off for a whole machine."""
    monkeypatch.setenv(DENY_NETWORK_ENV, value)
    assert network_denied() is False
    _policy().validate_url("https://www.fairfaxcounty.gov/x/query")


def test_the_switch_is_read_per_call_not_at_import(monkeypatch):
    """Set the variable inside a running process and the next request is
    refused, which is what lets one test set it and the next clear it."""
    assert network_denied() is False
    monkeypatch.setenv(DENY_NETWORK_ENV, "1")
    assert network_denied() is True
    monkeypatch.delenv(DENY_NETWORK_ENV)
    assert network_denied() is False


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


def _pin_spy(monkeypatch) -> list[httpx.Request]:
    """Stand in for the real socket at the layer below the pinned
    transport, and record the request as it was about to go out."""
    seen: list[httpx.Request] = []

    async def fake_send(self, request):
        seen.append(httpx.Request(request.method, request.url,
                                  headers=request.headers,
                                  extensions=dict(request.extensions)))
        return httpx.Response(200, content=b'{"ok":true}', request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request",
                        fake_send)
    return seen


async def test_the_connection_goes_to_the_address_the_policy_checked(
        monkeypatch):
    """Rule 3's second half (#16). The policy approved 93.184.216.34, so
    that is the address the connection is opened to — with the hostname
    still carried in the Host header and in the TLS handshake, so the
    certificate is checked against the name."""
    seen = _pin_spy(monkeypatch)
    await HttpFetcher(policy=_policy()).fetch_json(
        "https://www.fairfaxcounty.gov/x/query", {})
    assert len(seen) == 1
    sent = seen[0]
    assert sent.url.host == "93.184.216.34", (
        "the request was sent to a host the policy never approved")
    assert sent.headers["host"] == "www.fairfaxcounty.gov"
    assert sent.extensions["sni_hostname"] == "www.fairfaxcounty.gov"


async def test_a_second_dns_answer_cannot_change_the_address(monkeypatch):
    """The attack #16 describes: DNS with a very short TTL answers the
    policy's lookup with a public address and the connection's lookup with
    an internal one. There is no second lookup now, so the second answer
    is never reached — the resolver is called once and the connection uses
    what it returned."""
    answers = iter([[(2, 1, 6, "", ("93.184.216.34", 0))],
                    [(2, 1, 6, "", ("169.254.169.254", 0))]])
    calls = []

    def _flipping_resolver(host, _port):
        calls.append(host)
        return next(answers)

    seen = _pin_spy(monkeypatch)
    await HttpFetcher(policy=_policy(resolver=_flipping_resolver)).fetch_json(
        "https://www.fairfaxcounty.gov/x/query", {})
    assert calls == ["www.fairfaxcounty.gov"], (
        f"the hostname was resolved {len(calls)} times; the second answer "
        "is the one an attacker controls")
    assert seen[0].url.host == "93.184.216.34"


async def test_the_address_never_reaches_what_callers_read_back(monkeypatch):
    """The pinned address is a connection detail. `Response.url` reads
    through to the request, and the Code of Virginia publishes that URL as
    a section's source_url, so the hostname has to be restored."""
    _pin_spy(monkeypatch)
    fetcher = HttpFetcher(policy=_policy())
    body, _ = await fetcher._fetch("https://www.fairfaxcounty.gov/x", {})
    assert body.url == "https://www.fairfaxcounty.gov/x", body.url


async def test_every_approved_address_is_returned_in_resolution_order():
    """The resolver has already ordered its answer by preference, so the
    check keeps that order instead of collapsing it into a set."""
    def _two(host, _port):
        return [(2, 1, 6, "", ("93.184.216.34", 0)),
                (2, 1, 6, "", ("93.184.216.35", 0)),
                (2, 1, 6, "", ("93.184.216.34", 0))]

    approved = _policy(resolver=_two).validate_url(
        "https://www.fairfaxcounty.gov/x")
    assert approved == ("93.184.216.34", "93.184.216.35")


def _two_addresses(host, _port):
    return [(2, 1, 6, "", ("93.184.216.34", 0)),
            (2, 1, 6, "", ("93.184.216.35", 0))]


async def test_an_unreachable_address_falls_through_to_the_next(monkeypatch):
    """A host behind two addresses can have one of them unreachable, and
    both were approved by the same check.

    This is what replaces the happy-eyeballs behaviour that pinning took
    away. `getaddrinfo` returns AAAA records even with no IPv6 route and
    usually sorts them first, so a host publishing two of them ahead of
    any A record would otherwise never be reached at all."""
    seen: list[str] = []

    async def fake_send(self, request):
        seen.append(request.url.host)
        if request.url.host == "93.184.216.34":
            raise httpx.ConnectError("no route to host", request=request)
        return httpx.Response(200, content=b'{"ok":true}', request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request",
                        fake_send)
    monkeypatch.setattr("commonwealth.adapters.base.asyncio.sleep", _no_sleep)
    payload = await HttpFetcher(policy=_policy(resolver=_two_addresses)
                                ).fetch_json("https://www.fairfaxcounty.gov/x",
                                             {})
    assert payload == {"ok": True}
    assert seen == ["93.184.216.34", "93.184.216.35"], seen


async def test_walking_the_addresses_does_not_spend_the_retry_budget(
        monkeypatch):
    """The bug this closes: `approved[attempt % len(approved)]` gave each
    address its own attempt, so two unreachable addresses used up
    RETRY_BUDGET + 1 and a genuinely flaky host got no retry at all."""
    attempts: list[str] = []

    async def fake_send(self, request):
        attempts.append(request.url.host)
        raise httpx.ConnectError("no route to host", request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request",
                        fake_send)
    monkeypatch.setattr("commonwealth.adapters.base.asyncio.sleep", _no_sleep)
    with pytest.raises(SourceUnavailable, match="after 2 attempts"):
        await HttpFetcher(policy=_policy(resolver=_two_addresses)).fetch_json(
            "https://www.fairfaxcounty.gov/x", {})
    # Two addresses per attempt, RETRY_BUDGET + 1 attempts.
    assert attempts == ["93.184.216.34", "93.184.216.35"] * 2, attempts


async def test_a_redirect_keeps_the_query_the_location_header_gave(
        monkeypatch):
    """`params={}` is not "no params" in httpx: it REPLACES the query. A
    government host redirecting `.../query?where=...` to its canonical
    name was re-asked for a bare `.../query`, which answers with an HTML
    form and reads as an outage."""
    seen: list[str] = []

    async def fake_send(self, request):
        seen.append(str(request.url))
        if len(seen) == 1:
            return httpx.Response(
                301, headers={"location":
                              "https://www.fairfaxcounty.gov/moved"
                              "?where=PIN%3D%27123%27&f=json"},
                request=request)
        return httpx.Response(200, content=b'{"ok":true}', request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request",
                        fake_send)
    await HttpFetcher(policy=_policy()).fetch_json(
        "https://www.fairfaxcounty.gov/x/query", {"f": "json"})
    assert "where=PIN" in seen[1], seen
    assert "f=json" in seen[1], seen


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
