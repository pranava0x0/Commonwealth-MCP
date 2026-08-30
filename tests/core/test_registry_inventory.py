"""Proposed manifests (GitHub issues #2 and #9): a registry row that
describes no endpoint.

The activation gates in `validate_manifest` are what make the shape safe —
inventory is the only place a manifest may skip a terms review, a health
probe, and a capability claim, and an active manifest may skip none of
them. Each gate gets a mutation test, because a gate with no test is a
comment.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from commonwealth.core.registry import (DeclaredState, SourceManifest,
                                        SourceRegistry, validate_manifest)
from commonwealth.runtime import SOURCES_DIR

PROPOSED_PATH = SOURCES_DIR / "state" / "vdh.yaml"


def _load(path=PROPOSED_PATH) -> SourceManifest:
    return SourceManifest.model_validate(yaml.safe_load(path.read_text()))


def _problems(manifest: SourceManifest, vocab: set[str],
              jurisdictions: set[str]) -> list[str]:
    return [p.problem for p in
            validate_manifest(manifest, "test", vocab, jurisdictions)]


@pytest.fixture()
def vocab() -> set[str]:
    return SourceRegistry.load(SOURCES_DIR).capability_vocab


def test_the_proposed_vdh_manifest_validates_as_inventory(vocab):
    m = _load()
    assert m.lifecycle.declared_state == DeclaredState.proposed
    assert m.adapter.type == "none"
    assert m.access.terms_reviewed_at is None
    assert m.capabilities == []
    assert _problems(m, vocab, {"va"}) == []


def test_the_absence_is_recorded_with_the_date_it_was_checked():
    """GitHub issue #9's first acceptance criterion: an absence recorded
    with evidence closes the issue, an absence assumed does not."""
    m = _load()
    dated = [lim for lim in m.coverage.known_limitations
             if "2026-08-29" in lim]
    assert len(dated) >= 3, (
        "the VDH finding must name what was checked and when; found "
        f"{len(dated)} dated limitation(s)")
    joined = " ".join(m.coverage.known_limitations)
    assert "NXDOMAIN" in joined, "the DNS finding is the primary evidence"
    assert "data.virginia.gov" in joined, (
        "the portal check is the second half of the finding — VDH does "
        "publish, just not in a routable shape")


@pytest.mark.parametrize("mutation,expected", [
    ({"lifecycle": {"declared_state": "active"}},
     "adapter type 'none'"),
    ({"health": {"probe": "arcgis_layer_count"},
      "adapter": {"type": "virginia_law",
                  "service_url": "https://law.lis.virginia.gov/vacode"},
      "access": {"automation_status": "public_api"},
      "lifecycle": {"declared_state": "active"}},
     "terms_reviewed_at"),
])
def test_activation_gates_refuse_an_inventory_row_promoted_in_place(
        mutation, expected, vocab):
    """Mutation check: flipping declared_state on this file must fail, and
    must keep failing as each missing piece is filled in. A gate that only
    the happy path exercises is not a gate."""
    doc = copy.deepcopy(yaml.safe_load(PROPOSED_PATH.read_text()))
    for key, patch in mutation.items():
        doc[key] = {**(doc.get(key) or {}), **patch}
    problems = _problems(SourceManifest.model_validate(doc), vocab, {"va"})
    assert any(expected in p for p in problems), (
        f"expected a problem naming {expected!r}; got {problems}")


def test_an_active_manifest_still_needs_a_terms_review(vocab):
    """The field became optional; it must not have become optional for the
    sources that actually get queried."""
    doc = copy.deepcopy(yaml.safe_load(
        (SOURCES_DIR / "state" / "vgin-parcels.yaml").read_text()))
    assert _problems(SourceManifest.model_validate(doc), vocab, {"va"}) == []
    doc["access"].pop("terms_reviewed_at")
    problems = _problems(SourceManifest.model_validate(doc), vocab, {"va"})
    assert any("terms_reviewed_at" in p for p in problems), problems


def test_a_proposed_manifest_may_not_claim_a_capability(vocab):
    doc = copy.deepcopy(yaml.safe_load(PROPOSED_PATH.read_text()))
    doc["capabilities"] = [{"id": "parcel.lookup"}]
    problems = _problems(SourceManifest.model_validate(doc), vocab, {"va"})
    assert any("only an active manifest may declare capabilities" in p
               for p in problems), problems


def test_proposed_sources_are_never_selectable():
    """The gates are validation-time; this is the runtime half. A proposed
    row must not reach `select()` even for a capability it could answer."""
    registry = SourceRegistry.load(SOURCES_DIR)
    proposed = [m for m in registry.manifests.values()
                if m.lifecycle.declared_state == DeclaredState.proposed]
    assert proposed, "no proposed manifests — the coverage-debt split is 0"
    for capability in sorted(registry.capability_vocab):
        for m in registry.select(capability, ["va"]):
            assert m.lifecycle.declared_state == DeclaredState.active, (
                f"{m.id} is {m.lifecycle.declared_state} and was selected "
                f"for {capability}")
