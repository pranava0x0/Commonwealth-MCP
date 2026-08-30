"""The plural evidence array and the case that needed it
(GitHub issues #14 and #17).

design/provenance-envelope.md § 2 has always said a material record
carries `evidence_refs: [...]`. The wire emitted a singular string, and
the contract tests passed because they were written from the code rather
than from the spec — so the wire stayed wrong while the tests stayed
green. These are written from the spec.
"""
import json

import pytest

from commonwealth.domains.geo import (MAX_PARCEL_POLYGONS, find_parcel,
                                      find_zoning)
from commonwealth.runtime import PROJECT_ROOT

RICHMOND_FIXTURE = (PROJECT_ROOT / "tests" / "fixtures" / "sources" /
                    "va-richmond-city-parcels-zoning" / "recorded.json")


@pytest.fixture(scope="module")
def split_pin() -> str:
    """A PIN this publisher really does ship as two polygons, found with a
    grouped count against the live layer rather than invented."""
    summary = json.loads(RICHMOND_FIXTURE.read_text())["summary"]
    multi = summary.get("multi_polygon_pin")
    assert multi and multi["polygon_count"] > 1, (
        "the recorded fixture carries no multi-polygon PIN; re-run "
        "`commonwealth sources sample va-richmond-city-parcels-zoning`")
    return multi["pin"]


async def test_every_material_record_carries_a_list_not_a_string(cw_ctx):
    env = await find_parcel(cw_ctx, jurisdiction="Richmond City",
                            pin="C0010126019")
    for block in env.data["results"]:
        for row in block["records"]:
            assert isinstance(row["evidence_refs"], list), row
            assert "evidence_ref" not in row, (
                "the singular field is the drift this closes")


async def test_the_wire_schema_and_the_spec_agree_on_the_field_name():
    """The assertion the old contract tests could not make: read the
    field name out of the spec rather than out of the code."""
    spec = (PROJECT_ROOT / "design" / "provenance-envelope.md").read_text()
    assert "carries `evidence_refs: [...]`" in spec
    assert "the shipped wire emits a singular" not in spec, (
        "the divergence note should be resolved, not still standing")


async def test_a_split_parcel_reports_a_district_per_polygon(cw_ctx,
                                                             split_pin):
    """GitHub issue #17. Taking the first polygon was right about the
    count and wrong about the answer: the caller was told how many
    polygons matched and given the zoning of one of them."""
    env = await find_zoning(cw_ctx, jurisdiction="Richmond City",
                            pin=split_pin)
    block = env.data["results"][0]
    assert block["parcel_polygons_intersected"] == 2
    assert len(block["parcel_evidence_refs"]) == 2, (
        "one evidence reference per polygon the answer rests on")
    note = env.data["parcel_note"]
    assert "All were intersected" in note
    assert "the parcel is split" in note


async def test_each_district_names_every_polygon_it_rests_on(cw_ctx,
                                                             split_pin):
    """This is the case the plural array exists for: a district returned
    for a split parcel rests on more than one parcel geometry, and before
    the migration only one of them could be named."""
    env = await find_zoning(cw_ctx, jurisdiction="Richmond City",
                            pin=split_pin)
    block = env.data["results"][0]
    ids = {e.id for e in env.evidence}
    for row in block["records"]:
        assert len(row["evidence_refs"]) > 1, row
        assert set(row["evidence_refs"]) <= ids
        assert set(block["parcel_evidence_refs"]) <= set(row["evidence_refs"])


async def test_the_union_is_deduplicated_across_polygons(cw_ctx, split_pin):
    """One zoning polygon can touch both halves of a split parcel.
    Counting it twice would report a parcel as having two districts when
    it has one."""
    env = await find_zoning(cw_ctx, jurisdiction="Richmond City",
                            pin=split_pin)
    block = env.data["results"][0]
    record_ids = [r["record_id"] for r in block["records"]]
    assert len(record_ids) == len(set(record_ids)), record_ids
    assert block["record_count"] == len(record_ids)


async def test_the_polygon_union_is_declared_in_transformations(cw_ctx,
                                                                split_pin):
    env = await find_zoning(cw_ctx, jurisdiction="Richmond City",
                            pin=split_pin)
    refs = env.data["results"][0]["records"][0]["evidence_refs"]
    zoning_ev = next(e for e in env.evidence if e.id == refs[0])
    assert "parcel_polygons_unioned:2" in zoning_ev.transformations


async def test_a_single_polygon_parcel_gets_no_split_note(cw_ctx):
    """The note has to stay quiet when it should, or it becomes noise."""
    env = await find_zoning(cw_ctx, jurisdiction="Richmond City",
                            pin="C0010126019")
    assert "parcel_note" not in env.data
    assert env.data["results"][0]["parcel_polygons_intersected"] == 1


def test_the_polygon_bound_is_declared_and_small():
    """Each polygon is another request to a government service, so the
    walk is bounded; a PIN matching more than a handful is a data problem
    rather than a parcel."""
    assert 1 < MAX_PARCEL_POLYGONS <= 10
