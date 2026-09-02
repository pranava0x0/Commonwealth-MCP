"""The drift audit's judgement, tested without a network.

`tools/upstream_audit.py` is the one thing in this repo that is supposed to
reach live government services, so what can be tested offline is
everything except the reaching: what counts as drift, what does not, how
the readings accumulate, and whether the report keeps "checked and
unchanged" apart from "never visited" (GitHub issue #31).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import upstream_audit as audit  # noqa: E402


def _layer_info(fields: dict, **over) -> dict:
    doc = {"id": 0, "name": "Parcels", "type": "Feature Layer",
           "geometryType": "esriGeometryPolygon", "objectIdField": "OBJECTID",
           "fields": [{"name": n, "type": t} for n, t in fields.items()]}
    doc.update(over)
    return doc


def _query(rows: list[dict], geometry: bool = False) -> dict:
    return {"features": [{"attributes": r,
                          **({"geometry": {"rings": [[[0, 0]]]}}
                             if geometry else {})}
                         for r in rows]}


# --- what is drift --------------------------------------------------------

def test_a_renamed_field_is_drift():
    before = _layer_info({"PIN": "esriFieldTypeString"})
    after = _layer_info({"PARCEL_ID": "esriFieldTypeString"})
    notes = audit._diff(audit._shape(before), audit._shape(after))
    assert any("fields gone: PIN" in n for n in notes), notes
    assert any("fields added: PARCEL_ID" in n for n in notes), notes


def test_a_retyped_field_is_drift():
    """The real one this catches: a field numeric on one layer and text on
    every other, which is source-quirks.md § 5's whole subject."""
    before = _layer_info({"ZIP_5": "esriFieldTypeString"})
    after = _layer_info({"ZIP_5": "esriFieldTypeInteger"})
    notes = audit._diff(audit._shape(before), audit._shape(after))
    assert notes == ["field ZIP_5 changed type: esriFieldTypeString -> "
                     "esriFieldTypeInteger"], notes


def test_a_renumbered_layer_is_drift():
    notes = audit._diff(audit._shape(_layer_info({}, id=0)),
                        audit._shape(_layer_info({}, id=3)))
    assert any("layer id: 0 -> 3" in n for n in notes), notes


def test_a_layer_that_starts_erroring_is_drift():
    before = _query([{"PIN": "1"}])
    after = {"error": {"code": 500, "message": "Unable to complete"}}
    notes = audit._diff(audit._shape(before), audit._shape(after))
    assert any("error code" in n for n in notes), notes


def test_geometry_vanishing_is_drift():
    notes = audit._diff(audit._shape(_query([{"PIN": "1"}], geometry=True)),
                        audit._shape(_query([{"PIN": "1"}], geometry=False)))
    assert any("geometry present" in n for n in notes), notes


def test_a_moved_feature_count_is_drift():
    notes = audit._diff(audit._shape({"count": 369392}),
                        audit._shape({"count": 369394}))
    assert notes == ["count: 369392 -> 369394"], notes


# --- what is not ----------------------------------------------------------

def test_reordered_features_are_not_drift():
    """Structural, not byte-level. A publisher returning the same records
    in another order has changed nothing a caller depends on."""
    a = _query([{"PIN": "1"}, {"PIN": "2"}])
    b = _query([{"PIN": "2"}, {"PIN": "1"}])
    assert audit._diff(audit._shape(a), audit._shape(b)) == []


def test_changed_values_are_not_drift():
    """Government data changing is the data doing its job. What matters
    is the shape it arrives in."""
    a = _query([{"PIN": "1", "OWNER": "SMITH"}])
    b = _query([{"PIN": "1", "OWNER": "JONES"}])
    assert audit._diff(audit._shape(a), audit._shape(b)) == []


def test_an_identical_response_reports_nothing():
    doc = _layer_info({"PIN": "esriFieldTypeString"})
    assert audit._diff(audit._shape(doc), audit._shape(doc)) == []


# --- the accumulated readings (GitHub issue #19) --------------------------

def test_readings_accumulate_rather_than_overwrite():
    history = {"readings": []}
    audit.record_readings(history, "2026-09-01T00:00:00Z", {
        "va-x": [{"layer": "parcels", "feature_count": 100,
                  "min_expected": 80, "healthy": True}]})
    audit.record_readings(history, "2026-09-08T00:00:00Z", {
        "va-x": [{"layer": "parcels", "feature_count": 110,
                  "min_expected": 80, "healthy": True}]})
    assert len(history["readings"]) == 2
    seen = audit.observed_range(history, "va-x", "parcels")
    assert seen == {"observations": 2, "low": 100, "high": 110,
                    "spread_pct": 9.1}


def test_a_layer_with_no_readings_has_no_range():
    assert audit.observed_range({"readings": []}, "va-x", "parcels") is None


def test_two_runs_on_one_day_are_one_observation():
    """A floor's range should count days observed, not times run. Two
    runs twenty minutes apart say nothing about how much a count moves."""
    history = {"readings": []}
    probe = {"va-x": [{"layer": "parcels", "feature_count": 100,
                       "min_expected": 80, "healthy": True}]}
    audit.record_readings(history, "2026-09-01T07:00:00Z", probe)
    audit.record_readings(history, "2026-09-01T07:20:00Z", probe)
    assert audit.observed_range(history, "va-x", "parcels")[
        "observations"] == 1
    audit.record_readings(history, "2026-09-02T07:00:00Z", probe)
    assert audit.observed_range(history, "va-x", "parcels")[
        "observations"] == 2


def test_a_failed_probe_records_no_reading():
    """A failed probe reports an error where a count belongs. Recording
    it would put a zero into the range and drag every floor derived from
    it down."""
    history = {"readings": []}
    audit.record_readings(history, "2026-09-01T00:00:00Z", {
        "va-x": [{"layer": "parcels", "error": "SourceUnavailable: down"}]})
    assert history["readings"] == []


def test_the_backfill_is_idempotent(monkeypatch, tmp_path):
    """It reads the fixtures' own recorded counts, which are real dated
    observations that were going nowhere. Running it twice must not
    double them."""
    history = {"readings": []}
    first = audit.backfill_from_fixtures(history)
    assert first > 0, "no fixture carries a health block; the basis broke"
    again = audit.backfill_from_fixtures(history)
    assert again == 0
    assert len(history["readings"]) == first


def test_every_backfilled_reading_names_its_source_and_date():
    history = {"readings": []}
    audit.backfill_from_fixtures(history)
    for reading in history["readings"]:
        assert reading["observed_at"], reading
        assert reading["source_id"], reading
        assert isinstance(reading["feature_count"], int), reading


# --- the committed history stays usable -----------------------------------

def test_the_committed_history_gives_every_probed_layer_a_range():
    """What #19 asked for, asserted against the file that ships: no floor
    in a manifest rests on a single observation any more."""
    history = json.loads((ROOT / "docs" / "audits"
                          / "probe-history.json").read_text())
    pairs = {(r["source_id"], r["layer"]) for r in history["readings"]}
    assert pairs, "the history is empty"
    thin = [p for p in sorted(pairs)
            if audit.observed_range(history, *p)["observations"] < 2]
    assert thin == [], (
        f"{thin} still rest on one reading; run tools/upstream_audit.py")


def test_no_committed_floor_sits_above_the_lowest_reading():
    """A floor over the lowest count seen would report a healthy layer as
    broken, which is the failure #19 named in the other direction."""
    import yaml

    history = json.loads((ROOT / "docs" / "audits"
                          / "probe-history.json").read_text())
    bad = []
    for path in sorted((ROOT / "sources").rglob("*.yaml")):
        if "jurisdictions" in path.parts or path.name == "capabilities.yaml":
            continue
        doc = yaml.safe_load(path.read_text())
        if not isinstance(doc, dict) or not doc.get("id"):
            continue
        floors = ((doc.get("health") or {}).get("expect") or {}).get(
            "min_features")
        if not isinstance(floors, dict):
            continue
        for layer, floor in floors.items():
            seen = audit.observed_range(history, doc["id"], layer)
            if seen and floor > seen["low"]:
                bad.append(f"{doc['id']}/{layer}: floor {floor} > lowest "
                           f"reading {seen['low']}")
    assert bad == [], bad


# --- fixes from the 2026-09-02 review -------------------------------------

def test_row_order_alone_is_not_a_type_change():
    """`setdefault` kept the first feature's type, so a nullable column
    read as NoneType or str depending on which row arrived first. Eight
    committed fixtures already mix them."""
    a = _query([{"X": None}, {"X": "abc"}])
    b = _query([{"X": "abc"}, {"X": None}])
    assert audit._diff(audit._shape(a), audit._shape(b)) == []


def test_a_real_type_change_is_still_caught_behind_a_null():
    """The other half: a first value of None used to hide a genuine
    change for as long as it stayed first."""
    before = _query([{"X": None}, {"X": "abc"}])
    after = _query([{"X": None}, {"X": 7}])
    notes = audit._diff(audit._shape(before), audit._shape(after))
    assert any("changed type: str -> int" in n for n in notes), notes


def test_a_changed_projection_is_drift():
    """The module docstring names projections as a thing this catches,
    and `spatialReference` was the one field captured and never
    compared."""
    notes = audit._diff(
        audit._shape({"candidates": [], "spatialReference": {"wkid": 4326}}),
        audit._shape({"candidates": [], "spatialReference": {"wkid": 3857}}))
    assert any("spatial reference" in n for n in notes), notes


def test_a_renamed_geocoder_field_is_drift():
    """Candidate count alone would let the locator rename the fields the
    adapter reads and still pass as unchanged."""
    before = {"candidates": [{"address": "X", "score": 100,
                              "location": {"x": 1, "y": 2}}]}
    after = {"candidates": [{"addr": "X", "score": 100,
                             "location": {"x": 1, "y": 2}}]}
    notes = audit._diff(audit._shape(before), audit._shape(after))
    assert any("candidate fields gone: address" in n for n in notes), notes


def test_the_inventory_skip_matches_the_adapter_type_on_disk():
    """This held the literal "inventory" while every inventory manifest
    declares `none`, so four by-design non-probes were reported as
    missing recordings."""
    from commonwealth.core.registry import INVENTORY_ADAPTER

    assert audit.NO_ENDPOINT == {INVENTORY_ADAPTER}
    import yaml
    declared = {
        yaml.safe_load(path.read_text())["adapter"]["type"]
        for path in (ROOT / "sources").rglob("*.yaml")
        if "jurisdictions" not in path.parts
        and path.name != "capabilities.yaml"
        and isinstance(yaml.safe_load(path.read_text()), dict)
        and yaml.safe_load(path.read_text()).get("adapter")}
    assert audit.NO_ENDPOINT <= declared, (
        f"no manifest declares {audit.NO_ENDPOINT}; the skip is dead")


def test_a_null_count_is_not_recorded_as_a_reading():
    """`health()` tolerates a non-int count, so the key can be present
    holding None. Recording it put a null in the range #19's floors are
    derived from and crashed the report that formats it."""
    history = {"readings": []}
    audit.record_readings(history, "2026-09-09T00:00:00Z", {
        "va-x": [{"layer": "parcels", "feature_count": None,
                  "min_expected": 100, "healthy": False}]})
    assert history["readings"] == []


def test_an_unreachable_source_is_not_counted_as_changed():
    """A total outage read as thirteen changed sources, because every
    failed request appends a finding."""
    results = {
        "va-down": {"status": "unreachable", "checked": 0, "unreachable": 3,
                    "findings": [{"request": "q", "notes": ["failed"]}]},
        "va-fine": {"status": "checked", "checked": 2, "unreachable": 0,
                    "findings": []},
    }
    report = audit.render("2026-09-09T00:00:00Z", results, {},
                          {"readings": []})
    assert "- **0 changed**" in report, report
    assert "- **1 could not be reached**" in report, report
    assert "## Changed" not in report, report


def test_out_outside_the_repo_does_not_raise():
    """`relative_to` raised for any path outside the tree, after the
    report had already been written."""
    from pathlib import Path

    assert audit._short(Path("/tmp/elsewhere.md")) == Path("/tmp/elsewhere.md")
    assert audit._short(ROOT / "docs" / "x.md") == Path("docs/x.md")

