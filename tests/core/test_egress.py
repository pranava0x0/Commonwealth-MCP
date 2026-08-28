"""Every egress rule has its known-bad refusal (DECISIONS.md 0014 § 1: an
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


def test_no_default_credential_headers_exist():
    """Cross-host credential stripping is satisfied by construction in V1:
    the fetcher sends no auth headers at all. Pin that fact."""
    import inspect
    from commonwealth.adapters import base
    src = inspect.getsource(base.HttpFetcher)
    assert "Authorization" not in src and "headers=" not in src, (
        "HttpFetcher grew headers; implement redirect credential-stripping "
        "and replace this pin with real strip tests")
