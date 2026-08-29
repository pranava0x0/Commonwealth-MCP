"""Audit-record redaction (../../design/architecture.md decision 0014 § 3 structural minimization)."""
import yaml

from commonwealth.core.audit import error_record
from commonwealth.core.registry import SourceManifest
from commonwealth.runtime import SOURCES_DIR
from tests.conftest import build_ctx


def _sensitive_manifest() -> SourceManifest:
    doc = yaml.safe_load(
        (SOURCES_DIR / "local" / "fairfax-county" /
         "parcels-zoning.yaml").read_text())
    doc["id"] = "va-fairfax-sensitive-test"
    doc["access"]["data_classification"] = "sensitive_public"
    doc["access"]["exposure_allowlist"] = ["PIN"]
    doc["access"]["classification_reviewed_by"] = "test"
    doc["access"]["classification_reviewed_at"] = "2026-08-28"
    return SourceManifest.model_validate(doc)


def test_has_sensitive_sources_false_for_the_real_registry():
    ctx = build_ctx()
    assert ctx.has_sensitive_sources() is False, (
        "none of the committed sources are sensitive_public today")


def test_has_sensitive_sources_true_once_one_is_registered():
    ctx = build_ctx(extra_manifests=[_sensitive_manifest()])
    assert ctx.has_sensitive_sources() is True


def test_error_record_redacts_args_when_registry_has_sensitive_sources():
    """A failure can occur before it's known which source a call would
    have reached — the redaction has to be conservative (registry-wide),
    not conditioned on which source the failed call was actually headed
    for, or it fails open on exactly the calls it can't fully assess."""
    rec = error_record(
        tool="geo.find_parcel", args={"jurisdiction": "Fairfax County",
                                      "pin": "0102 14  0231"},
        error_code="invalid_query", duration_ms=5, server="commonwealth",
        server_version="0.1.0.dev0", registry_revision="2026-08-28",
        sensitive=True)
    assert rec.args is None
    assert rec.arg_names == ["jurisdiction", "pin"], (
        "argument NAMES stay visible even when values are redacted")


def test_error_record_keeps_args_when_nothing_is_sensitive():
    rec = error_record(
        tool="geo.find_parcel", args={"jurisdiction": "Fairfax County"},
        error_code="invalid_query", duration_ms=5, server="commonwealth",
        server_version="0.1.0.dev0", registry_revision="2026-08-28",
        sensitive=False)
    assert rec.args == {"jurisdiction": "Fairfax County"}
