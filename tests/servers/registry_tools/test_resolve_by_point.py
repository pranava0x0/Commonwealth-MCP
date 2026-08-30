"""Point-in-polygon jurisdiction resolution
(design/jurisdiction-resolution.md § 2-3). These are the traps the whole
jurisdiction model exists for, so they are asserted on real recorded
boundary responses, not on hand-written shapes."""
import pytest

from commonwealth.core.errors import InvalidQuery
from commonwealth.domains.registry import resolve_jurisdiction


async def test_point_in_independent_city_never_returns_the_county(cw_ctx):
    """§ 3.2, the canonical trap. A point inside Fairfax City must resolve
    to Fairfax City. Returning Fairfax County here would hand the user a
    different government's records and look entirely plausible."""
    env = await resolve_jurisdiction(cw_ctx, lon=-77.3064, lat=38.8462)
    assert env.data["resolved"]["id"] == "va:fairfax-city"
    assert env.data["resolved"]["basis"] == "point_in_polygon"
    assert "va:fairfax-county" not in {
        a["id"] for a in env.data["layered_authorities"]}


async def test_point_in_town_reports_town_and_its_county(cw_ctx):
    """§ 3.4: a town and its county both govern the same ground. The leaf
    alone is not the answer — 'whose zoning' and 'whose schools' differ."""
    env = await resolve_jurisdiction(cw_ctx, lon=-77.2653, lat=38.9012)
    assert env.data["resolved"]["id"] == "va:vienna-town"
    layered = {a["id"]: a["relationship"]
               for a in env.data["layered_authorities"]}
    assert layered["va:fairfax-county"] == "containing-locality"
    assert layered["va"] == "parent-state"


async def test_point_near_a_boundary_warns_instead_of_asserting(cw_ctx):
    """§ 3.7: a point hard against the Fairfax City/County line still
    resolves, but must carry boundary_precision naming the neighbour —
    the published line is cartographic, so the side is not settled."""
    env = await resolve_jurisdiction(cw_ctx, lon=-77.26917, lat=38.85378)
    assert env.data["resolved"]["id"] == "va:fairfax-county"
    assert env.data["nearby_jurisdictions"] == ["Fairfax City"]
    warning = next(w for w in env.warnings
                   if w.code.value == "boundary_precision")
    assert "Fairfax City" in warning.message


async def test_interior_point_does_not_cry_boundary(cw_ctx):
    """The straddle warning has to stay quiet when it should, or it becomes
    noise everyone learns to ignore."""
    env = await resolve_jurisdiction(cw_ctx, lon=-77.2500, lat=38.8000)
    assert env.data["resolved"]["id"] == "va:fairfax-county"
    assert "nearby_jurisdictions" not in env.data
    assert not [w for w in env.warnings
                if w.code.value == "boundary_precision"]


async def test_every_locality_the_boundary_source_knows_is_now_in_the_table(
        cw_ctx):
    """Issue #25's point. Virginia Beach used to come back as
    `unmapped_match` because the 14-row seed had no row for it. The table
    now carries all 133, so the same coordinate resolves."""
    env = await resolve_jurisdiction(cw_ctx, lon=-75.9780, lat=36.8529)
    assert env.data["resolved"]["id"] == "va:virginia-beach-city"
    assert env.data["resolved"]["fips"] == "51810"
    assert "unmapped_match" not in env.data


async def test_a_locality_missing_from_the_table_is_reported_not_discarded():
    """The unmapped path is still the drift alarm: if VGIN adds a locality
    the table does not carry, a sourced answer must not be thrown away —
    and must not be dressed up as a resolution either.

    The shipped table no longer has that gap, so the gap is made on
    purpose here. Deleting this test with the last unmapped row would
    leave the branch that handles the next one untested."""
    from commonwealth.core.jurisdiction import JurisdictionTable
    from tests.conftest import build_ctx

    ctx = build_ctx()
    full = ctx.jurisdictions
    ctx.jurisdictions = JurisdictionTable(
        [full.get(jid) for jid in sorted(full.ids())
         if jid != "va:virginia-beach-city"])
    env = await resolve_jurisdiction(ctx, lon=-75.9780, lat=36.8529)
    assert env.data["resolved"] is None
    unmapped = env.data["unmapped_match"]
    assert unmapped["source_name"] == "Virginia Beach City"
    assert unmapped["source_fips"] == "51810"
    assert "the gap is ours" in unmapped["note"]
    assert env.coverage.result.value == "hit", (
        "a real polygon was found; 'empty' would misreport it as nowhere")


async def test_point_outside_virginia_is_empty_and_says_why(cw_ctx):
    env = await resolve_jurisdiction(cw_ctx, lon=-74.5, lat=36.5)
    assert env.data["resolved"] is None
    assert env.coverage.result.value == "empty"
    assert env.coverage.execution.value == "complete", (
        "the source answered; 'failed' would confuse a gap with an outage")
    assert "outside the Commonwealth" in env.data["note"]


async def test_name_and_point_together_are_refused(cw_ctx):
    """§ 2: more than one input is an error naming the conflict, never a
    silent precedence rule that hides a contradiction."""
    with pytest.raises(InvalidQuery, match="not both"):
        await resolve_jurisdiction(cw_ctx, query="Fairfax County",
                                   lon=-77.25, lat=38.8)


async def test_half_a_point_is_refused(cw_ctx):
    with pytest.raises(InvalidQuery, match="both lon and lat"):
        await resolve_jurisdiction(cw_ctx, lon=-77.25)


async def test_no_input_at_all_is_refused(cw_ctx):
    with pytest.raises(InvalidQuery):
        await resolve_jurisdiction(cw_ctx)


async def test_name_resolution_still_works(cw_ctx):
    """The point path is additive; the existing contract must be untouched."""
    env = await resolve_jurisdiction(cw_ctx, "Fairfax County")
    assert env.data["resolved"]["id"] == "va:fairfax-county"
    assert env.data["resolved"]["basis"] == "exact_name"


async def test_point_resolution_carries_government_provenance(cw_ctx):
    """A point answer is sourced from VGIN, not from project data — the
    envelope must name the government layer that actually decided it."""
    env = await resolve_jurisdiction(cw_ctx, lon=-77.3064, lat=38.8462)
    assert [s.source_id for s in env.provenance] == [
        "va-vgin-admin-boundaries"]
    assert env.evidence and all(
        e.source_ref == env.provenance[0].id for e in env.evidence)
