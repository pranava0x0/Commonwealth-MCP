"""geo.find_roads over two publishers (GitHub issue #5).

Roads are decision 0005's second standing example after parcels, and a
better one: an operating agency's route inventory and an aggregation of
local centerline submissions describe the same ground differently ON
PURPOSE, so a disagreement here is the expected case rather than the edge
one.
"""
import pytest

from commonwealth.core.errors import InvalidQuery
from commonwealth.domains.geo import find_roads


async def test_both_sources_answer_and_neither_is_ranked(cw_ctx):
    env = await find_roads(cw_ctx, jurisdiction="Vienna",
                           street_name="Center St")
    assert {blk["source_id"] for blk in env.data["results"]} == {
        "va-vdot-lrs-routes", "va-vgin-road-centerlines"}


async def test_the_two_publishers_disagree_and_the_answer_says_so(cw_ctx):
    """Live on 2026-08-29: VDOT's LRS calls the road "Center ST N (PR -
    Town of Vienna)" and carries 2 routes; VGIN's centerlines call it
    "Center St N" and carry 39 segments. Same road, different model."""
    env = await find_roads(cw_ctx, jurisdiction="Vienna",
                           street_name="Center St")
    by_source = {blk["source_id"]: blk for blk in env.data["results"]}
    assert by_source["va-vdot-lrs-routes"]["record_count"] == 2
    assert by_source["va-vgin-road-centerlines"]["record_count"] == 39
    comparison = env.data["comparison"]
    assert comparison["agreement"] is False
    assert "not an error in either" in comparison["note"]


async def test_a_source_with_nothing_to_compare_is_not_a_disagreement(
        cw_ctx):
    """VDOT keys routes on the TOWN, so a county-scoped query finds none
    of Vienna's streets in it while VGIN finds all 39. That is a
    different fact from the two sources contradicting each other."""
    env = await find_roads(cw_ctx, jurisdiction="Fairfax County",
                           street_name="Center St")
    by_source = {blk["source_id"]: blk for blk in env.data["results"]}
    assert by_source["va-vdot-lrs-routes"]["record_count"] == 0
    assert by_source["va-vgin-road-centerlines"]["record_count"] == 39
    comparison = env.data["comparison"]
    assert comparison["agreement"] is None
    assert "nothing to compare" in comparison["note"]


async def test_a_centerline_source_matches_either_side_of_a_road(cw_ctx):
    """A road on a locality line carries a different FIPS on each side, so
    "in this locality" is an OR. An AND would return only roads with the
    same locality on both sides and silently drop every boundary road."""
    from commonwealth.domains.geo import _jurisdiction_filter
    m = cw_ctx.sources.get("va-vgin-road-centerlines")
    groups = _jurisdiction_filter(cw_ctx, m, "centerlines",
                                  ["va:fairfax-county", "va"])
    assert groups == [{"fips_left": "51059"}, {"fips_right": "51059"}]


async def test_the_vdot_source_is_scoped_by_name_not_by_fips(cw_ctx):
    """RTE_JURIS_CD is VDOT's own numbering, not FIPS — City of Manassas
    is "155" there. The scoping key is the name field instead."""
    from commonwealth.domains.geo import _jurisdiction_filter
    m = cw_ctx.sources.get("va-vdot-lrs-routes")
    groups = _jurisdiction_filter(cw_ctx, m, "routes",
                                  ["va:vienna-town", "va:fairfax-county",
                                   "va"])
    assert {"jurisdiction_name": "Town of Vienna"} in groups
    # The table's own name carries a "(town)" suffix the publisher does
    # not use, so it must not be sent.
    assert not any("(" in list(g.values())[0] for g in groups)


async def test_by_point_with_a_radius(cw_ctx):
    env = await find_roads(cw_ctx, jurisdiction="Vienna",
                           lon=-77.2653, lat=38.9012)
    counts = {blk["source_id"]: blk["record_count"]
              for blk in env.data["results"]}
    assert counts["va-vgin-road-centerlines"] == 4
    assert counts["va-vdot-lrs-routes"] == 2


async def test_a_screening_warning_says_a_centerline_is_not_a_boundary(
        cw_ctx):
    env = await find_roads(cw_ctx, jurisdiction="Vienna",
                           street_name="Center St")
    warning = next(w for w in env.warnings
                   if w.code.value == "screening_only")
    assert "right-of-way boundary" in warning.message


async def test_no_match_is_empty_on_both_sources(cw_ctx):
    env = await find_roads(cw_ctx, jurisdiction="Fairfax County",
                           street_name="ZZZZ NO SUCH ROAD")
    assert all(blk["record_count"] == 0 for blk in env.data["results"])
    assert env.coverage.result.value == "empty"
    assert env.coverage.execution.value == "complete"


def test_the_registered_centerline_layer_is_the_complete_one():
    """Layers 1 and 2 are road-class subsets and layer 5 is layer 4 at a
    different map scale (identical 659,179 counts and 58-field schemas,
    read live 2026-08-29). Registering a subset and calling it "roads"
    would exclude 585,000 local roads."""
    import yaml
    from commonwealth.runtime import SOURCES_DIR
    doc = yaml.safe_load(
        (SOURCES_DIR / "state" / "vgin-road-centerlines.yaml").read_text())
    layers = doc["adapter"]["layers"]
    assert layers["centerlines"]["layer_id"] == 4
    floors = doc["health"]["expect"]["min_features"]
    assert floors["centerlines"] > floors["primaries"] * 5, (
        "the two layers are two orders of magnitude apart; one shared "
        "floor would be useless, which is what per-layer floors are for")


@pytest.mark.parametrize("kwargs,fragment", [
    ({}, "exactly one"),
    ({"street_name": "x", "lon": 1.0, "lat": 2.0}, "exactly one"),
    ({"lon": 1.0}, "both lon and lat"),
])
async def test_bad_inputs_are_refused_by_name(cw_ctx, kwargs, fragment):
    with pytest.raises(InvalidQuery) as err:
        await find_roads(cw_ctx, jurisdiction="Vienna", **kwargs)
    assert fragment in str(err.value)
