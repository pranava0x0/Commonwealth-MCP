"""Egress policy (design/security-and-data-handling.md § 2; ../../../design/architecture.md decision 0014, frozen).

Adapters are the only outbound path, and every request URL passes through
`EgressPolicy.validate_url` immediately before use. DNS is resolved and
checked here, at request time, and `validate_url` hands the approved
addresses back so the connection can be made to one of them rather than to
whatever a second lookup returns (#16, fixed 2026-09-01). The transport
that does the pinning lives in adapters/base.py, which is where httpx
lives; this module stays free of the HTTP client.

Every rule has a known-bad fixture in tests/core/test_egress.py that must be
refused — an egress rule without its refusal test is prose, not policy.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .errors import EgressRefused

MAX_RESPONSE_BYTES = 20_000_000
MAX_REDIRECTS = 3

# The deny switch. Set it and every host is refused before DNS is even
# resolved, which turns "these tests run offline" from a habit into a
# property the process enforces. The test suite exports it, and so can CI.
#
# It lives in the policy rather than in a test helper because it is policy
# behaviour: an operator running the CLI on a machine that must not talk to
# a government service gets the same refusal, through the same typed error,
# as a test does.
DENY_NETWORK_ENV = "COMMONWEALTH_DENY_NETWORK"


def network_denied() -> bool:
    """Whether the deny switch is on.

    Read on every call rather than at import, so setting the variable
    inside a running process takes effect and a test can turn it on and
    off. Empty and "0" mean off; every other value means on.
    """
    return os.environ.get(DENY_NETWORK_ENV, "").strip() not in ("", "0")


# Rule 6 has two halves and the byte cap is only one of them. A gzipped
# response is small on the wire and large once decoded, so a body well
# under MAX_RESPONSE_BYTES of transfer can still expand past any memory
# budget. The cap and the ratio are checked separately.
#
# 50x is far above what real government JSON and HTML achieve. Measured
# over this project's own recorded fixtures: 4.6x to 18.1x. A payload
# compressing better than 50x is not the shape of data these sources
# publish.
MAX_DECOMPRESSION_RATIO = 50

# Below this the ratio is meaningless: a 200-byte response from a 4-byte
# compressed frame is 50x and entirely ordinary.
DECOMPRESSION_RATIO_FLOOR_BYTES = 64_000
_SHARED_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local (includes cloud metadata)"
    if ip.is_private:
        return "private range"
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return "non-unicast/reserved"
    if ip.version == 4 and ip in _SHARED_CGNAT:
        return "shared CGNAT range"
    return None


@dataclass
class EgressPolicy:
    """One policy instance per source manifest."""

    allowed_hosts: frozenset[str]
    insecure_transport: bool = False
    allowed_ports: frozenset[int] = field(default_factory=frozenset)
    resolver: object = None  # test seam; defaults to socket.getaddrinfo

    def validate_url(self, url: str) -> tuple[str, ...]:
        """Check one URL against every rule.

        Returns the addresses the host resolved to, in the order the
        resolver gave them, so the caller can connect to one of these
        rather than resolving the name a second time.
        """
        if network_denied():
            raise EgressRefused(
                f"{DENY_NETWORK_ENV} is set, so every host is refused and "
                f"no request was sent for {url!r}. Unset it to allow "
                "outbound requests.")

        parsed = urlparse(url)

        if parsed.scheme == "http":
            if not self.insecure_transport:
                raise EgressRefused(
                    f"plain http refused for {parsed.hostname!r}; the source "
                    "manifest does not declare insecure_transport")
        elif parsed.scheme != "https":
            raise EgressRefused(f"scheme {parsed.scheme!r} refused; only "
                                "https (or manifest-declared http) is allowed")

        host = parsed.hostname
        if not host:
            raise EgressRefused(f"URL has no host: {url!r}")

        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise EgressRefused(
                f"IP-literal host {host!r} refused; register a hostname in "
                "the source manifest")

        if host.lower() not in self.allowed_hosts:
            raise EgressRefused(
                f"host {host!r} is not in this source's registered host set "
                f"{sorted(self.allowed_hosts)}")

        port = parsed.port
        default_ports = {443} | ({80} if self.insecure_transport else set())
        permitted = default_ports | set(self.allowed_ports)
        if port is not None and port not in permitted:
            raise EgressRefused(f"port {port} refused; permitted: "
                                f"{sorted(permitted)}")

        return self._check_dns(host)

    def _check_dns(self, host: str) -> tuple[str, ...]:
        resolver = self.resolver or socket.getaddrinfo
        try:
            infos = resolver(host, None)
        except OSError as err:
            raise EgressRefused(f"DNS resolution failed for {host!r}: "
                                f"{err.__class__.__name__}") from err
        # Resolution order is kept rather than collapsed into a set: the
        # resolver has already sorted the addresses by preference and the
        # caller connects to the first one.
        addrs: list[str] = []
        for info in infos:
            raw = info[4][0]
            if raw not in addrs:
                addrs.append(raw)
        if not addrs:
            raise EgressRefused(f"DNS returned no addresses for {host!r}")
        for raw in addrs:
            ip = ipaddress.ip_address(raw.split("%")[0])
            reason = _blocked_ip(ip)
            if reason:
                raise EgressRefused(
                    f"{host!r} resolves to {ip} ({reason}); refusing")
        # Every address is checked, and every address is returned: refusing
        # one member of the set refuses the whole request, so a caller can
        # connect to any of these knowing all of them passed.
        return tuple(a.split("%")[0] for a in addrs)

    def validate_redirect(self, from_url: str, location: str,
                          hop_count: int) -> str:
        """Validate one redirect hop; returns the absolute target URL.

        The caller re-validates that URL before connecting, which is where
        the approved addresses for the hop come from.
        """
        if hop_count > MAX_REDIRECTS:
            raise EgressRefused(f"redirect chain exceeded {MAX_REDIRECTS} hops")
        from urllib.parse import urljoin
        target = urljoin(from_url, location)
        self.validate_url(target)
        return target


def hosts_from_url(url: str) -> frozenset[str]:
    host = urlparse(url).hostname
    if not host:
        raise ValueError(f"cannot derive host from {url!r}")
    return frozenset({host.lower()})
