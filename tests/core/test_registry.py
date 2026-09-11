"""Source-registry gates and top-two selection (../../design/architecture.md decision 0005 Chosen)."""
import pytest
import yaml

import commonwealth.adapters  # noqa: F401  registers adapter params
from commonwealth.core.registry import (DeclaredState, OperationalState,
                                        SourceManifest, SourceRegistry,
                                        validate_manifest)
from commonwealth.runtime import SOURCES_DIR

KNOWN_J = {"va", "va:fairfax-county"}
VOCAB = {"parcel.lookup", "zoning.lookup"}


def _manifest(**overrides) -> SourceManifest:
    path = SOURCES_DIR / "local" / "fairfax-county" / "parcels-zoning.yaml"
    doc = yaml.safe_load(path.read_text())
    for dotted, value in overrides.items():
        node = doc
        *parents, leaf = dotted.split(".")
        for p in parents:
            node = node[p]
        node[leaf] = value
    return SourceManifest.model_validate(doc)


def _problems(m: SourceManifest) -> list[str]:
    return [p.problem for p in validate_manifest(m, "test", VOCAB, KNOWN_J)]


def test_real_manifest_is_valid():
    assert _problems(_manifest()) == []


def test_active_requires_activatable_automation_status():
    m = _manifest(**{"access.automation_status": "manual_review_required"})
    assert any("declared_state=active requires" in p for p in _problems(m))


def test_restricted_classification_cannot_activate():
    m = _manifest(**{"access.data_classification": "restricted"})
    assert any("restricted" in p for p in _problems(m))


def test_sensitive_public_requires_allowlist_and_reviewer():
    m = _manifest(**{"access.data_classification": "sensitive_public"})
    probs = _problems(m)
    assert any("exposure_allowlist" in p for p in probs)
    assert any("classification_reviewed_by" in p for p in probs)


def test_unknown_capability_fails():
    m = _manifest()
    assert any("not in the vocabulary" in p
               for p in [q.problem for q in validate_manifest(
                   m, "t", {"zoning.lookup"}, KNOWN_J)])


def test_unknown_jurisdiction_fails():
    assert any("jurisdiction table" in p
               for p in [q.problem for q in validate_manifest(
                   _manifest(), "t", VOCAB, {"va"})])


def test_bad_adapter_params_fail():
    m = _manifest(**{"adapter.layers": {"parcels": {"layer_id": "not-an-int",
                                                    "field_mapping": {},
                                                    "geometry": "polygon",
                                                    "id_field": "OBJECTID"}}})
    assert any("adapter params invalid" in p for p in _problems(m))


# --- selection (0005-C) ----------------------------------------------------

def _mini_registry(*levels: str,
                   states: dict[int, str] | None = None) -> SourceRegistry:
    manifests = []
    for i, level in enumerate(levels):
        manifests.append(_manifest(**{
            "id": f"src-{i}",
            "publisher.authority_level": level,
            "lifecycle.declared_state": (states or {}).get(i, "active"),
        }))
    return SourceRegistry(manifests, VOCAB, "test")


def test_select_returns_at_most_two_ordered_by_authority():
    reg = _mini_registry("third_party", "primary", "official_secondary")
    sel = reg.select("zoning.lookup", ["va:fairfax-county"])
    assert [m.id for m in sel] == ["src-1", "src-2"], (
        "top two by authority, third_party left out")


def test_select_skips_proposed_and_unavailable():
    reg = _mini_registry("primary", "official_secondary",
                         states={0: "proposed"})
    reg.set_operational("src-1", OperationalState.unavailable)
    assert reg.select("zoning.lookup", ["va:fairfax-county"]) == []
    reasons = dict(reg.unavailable_for("zoning.lookup", ["va:fairfax-county"]))
    assert reasons["va:fairfax-county"] in ("source_unavailable",
                                            "source_not_activated")


def test_unavailable_for_distinguishes_gap_from_outage():
    reg = _mini_registry("primary")
    assert reg.unavailable_for("zoning.lookup", ["va:craig-county"]) == [
        ("va:craig-county", "no_registered_source")]
    reg.set_operational("src-0", OperationalState.unavailable)
    assert reg.unavailable_for("zoning.lookup", ["va:fairfax-county"]) == [
        ("va:fairfax-county", "source_unavailable")]


def test_impaired_stays_selectable():
    reg = _mini_registry("primary")
    reg.set_operational("src-0", OperationalState.impaired)
    assert [m.id for m in reg.select("zoning.lookup",
                                     ["va:fairfax-county"])] == ["src-0"]


def test_real_sources_dir_loads_and_counts():
    reg = SourceRegistry.load(SOURCES_DIR)
    assert len(reg.manifests) >= 1
    assert "zoning.lookup" in reg.capability_vocab
    print(f"registry loaded: {len(reg.manifests)} manifest(s), "
          f"{len(reg.capability_vocab)} capabilities")


def test_load_rejects_a_manifest_that_fails_activation_gates(tmp_path):
    """`commonwealth sources validate` catching a gate violation is not
    enough — the runtime load path (used by every real tool call) must
    refuse it too, or a deployment started against a modified source
    directory could serve a manifest CI never checked."""
    import shutil
    shutil.copytree(SOURCES_DIR / "jurisdictions",
                    tmp_path / "jurisdictions")
    shutil.copy(SOURCES_DIR / "capabilities.yaml", tmp_path)
    doc = yaml.safe_load(
        (SOURCES_DIR / "local" / "fairfax-county" /
         "parcels-zoning.yaml").read_text())
    doc["access"]["data_classification"] = "restricted"
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump(doc))
    with pytest.raises(ValueError, match="activation gates"):
        SourceRegistry.load(tmp_path)


# --- health floors the probe can read ---------------------------------------

def test_health_floors_under_an_unread_key_are_refused():
    """`expect: {parcels: {min_expected: 100000}}` is a floor nothing
    reads: the probe falls back to 1, and a layer answering with a single
    feature passes as healthy. Two manifests shipped that way (found in
    review of PR #56)."""
    m = _manifest(**{"health.expect": {"parcels": {"min_expected": 100000}}})
    assert any("not read for ['parcels']" in p for p in _problems(m))


def test_health_floors_must_name_declared_layers():
    m = _manifest(**{"health.expect": {"min_features": {"buildings": 5}}})
    assert any("does not declare: ['buildings']" in p for p in _problems(m))


@pytest.mark.parametrize("floors", [
    {"parcels": 0}, {"parcels": "many"}, {"parcels": True}, "lots",
])
def test_health_floors_are_whole_numbers(floors):
    m = _manifest(**{"health.expect": {"min_features": floors}})
    assert any("whole number" in p for p in _problems(m))


def test_the_floors_a_manifest_declares_are_the_floors_the_probe_uses():
    """Through the real probe over the recorded count, for the manifests
    that had it wrong."""
    import asyncio

    from commonwealth.fixtures import replay_context

    ctx = replay_context()
    for source_id, layer, floor in (
            ("va-loudoun-county-parcels-zoning", "parcels", 100_000),
            ("va-loudoun-county-parcels-zoning", "zoning", 1_000),
            ("va-loudoun-county-health-facilities", "health_facilities", 5)):
        result = asyncio.run(ctx.arcgis.health(ctx.sources.get(source_id),
                                               layer))
        assert result["min_expected"] == floor, (source_id, layer, result)
        assert result["healthy"] is True, (source_id, layer, result)
