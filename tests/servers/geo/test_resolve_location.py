"""Address and ZIP resolution (GitHub issue #3,
design/jurisdiction-resolution.md § 3 cases 1, 4, and 5).

These are the postal-city traps the whole jurisdiction model exists for,
and until a geocoder was registered none of them could be regression-
tested. They run against recorded responses from VGIN's composite locator
and its address-point layer, not hand-written shapes.
"""
import pytest

from commonwealth.core.errors import InvalidQuery
from commonwealth.domains.geo import resolve_location


async def test_case_1_a_mailing_city_is_not_the_government(cw_ctx):
    """§ 3.1. "Alexandria, VA 22310" is a Fairfax County address. An agent
    that reads the mailing city as the jurisdiction gets an entirely
    plausible wrong government's records."""
    env = await resolve_location(
        cw_ctx, address="6800 Beulah St, Alexandria, VA 22310")
    assert env.data["resolved"]["id"] == "va:fairfax-county"
    assert env.data["resolved"]["basis"] == "geocode_then_point_in_polygon"
    assert env.data["geocode"]["postal_city"] == "ALEXANDRIA"
    note = env.data["postal_city_note"]
    assert "Alexandria" in note and "Fairfax County" in note


async def test_case_4_a_town_address_returns_the_town_and_its_county(cw_ctx):
    """§ 3.4. Both governments apply at that ground, so the leaf alone is
    not the answer. This is the case that was explicitly NOT counted as
    built by the point path, because it names an address."""
    env = await resolve_location(
        cw_ctx, address="127 Center St S, Vienna, VA 22180")
    assert env.data["resolved"]["id"] == "va:vienna-town"
    layered = {a["id"]: a["relationship"]
               for a in env.data["layered_authorities"]}
    assert layered["va:fairfax-county"] == "containing-locality"
    assert layered["va"] == "parent-state"


async def test_case_5_a_multi_locality_zip_returns_candidates(cw_ctx):
    """§ 3.5. A one-to-many ZIP that resolves to one jurisdiction is a bug,
    not a convenience.

    The spec named this case as "Lexington + Rockbridge County mix". The
    real data has three: Botetourt County is in it too, which is why the
    assertion is against what the publisher returned rather than against
    the two the spec remembered."""
    env = await resolve_location(cw_ctx, zip_code="24450")
    assert env.data["resolved"] is None
    assert env.requires_user_choice is True
    ids = sorted(c["id"] for c in env.data["candidates"])
    assert ids == ["va:botetourt-county", "va:lexington-city",
                   "va:rockbridge-county"]
    assert all(c["distinguisher"] for c in env.data["candidates"])


async def test_a_single_locality_zip_resolves(cw_ctx):
    """The discipline has to cut both ways: refusing to answer a ZIP that
    genuinely covers one locality would make the tool useless."""
    env = await resolve_location(cw_ctx, zip_code="22180")
    assert env.data["resolved"]["id"] == "va:fairfax-county"
    assert env.data["resolved"]["basis"] == "zip_unique"
    assert env.requires_user_choice is False


async def test_a_zip_with_no_address_points_is_empty_not_wrong(cw_ctx):
    env = await resolve_location(cw_ctx, zip_code="00000")
    assert env.data["resolved"] is None
    assert env.coverage.result.value == "empty"
    assert env.coverage.execution.value == "complete", (
        "the source answered; 'failed' would confuse a gap with an outage")
    assert "not proof the ZIP does not exist" in env.data["note"]


async def test_an_unmatched_address_returns_no_guess(cw_ctx):
    env = await resolve_location(cw_ctx, address="zzzz nowhere at all qqq")
    assert env.data["resolved"] is None
    assert env.data["candidates"] == []
    assert env.coverage.result.value == "empty"
    assert "outside Virginia" in env.data["note"]


async def test_the_geocode_step_is_visible_in_the_envelope(cw_ctx):
    """A geocode is a transformation of the caller's input into a
    coordinate, and it has to be inspectable — the locator, its score, and
    which of its elements answered."""
    env = await resolve_location(
        cw_ctx, address="127 Center St S, Vienna, VA 22180")
    geo = env.data["geocode"]
    assert geo["matched_by"] == "AddressPoint"
    assert geo["score"] >= geo["min_score"]
    ev = next(e for e in env.evidence
             if e.id == geo["evidence_refs"][0])
    assert "geocode:findAddressCandidates" in ev.transformations
    src = next(s for s in env.provenance if s.id == geo["source_ref"])
    assert src.source_id == "va-vgin-composite-locator"
    assert src.system == "arcgis_geocode"
    # Two sources: the locator and the boundary layer. A geocode that
    # reported only the locator would hide where the jurisdiction came
    # from.
    assert {s.source_id for s in env.provenance} == {
        "va-vgin-composite-locator", "va-vgin-admin-boundaries"}


async def test_a_bare_zip_geocode_is_not_used_as_a_resolution(cw_ctx):
    """The locator happily geocodes "24450" to one centroid in Lexington.
    Routing the ZIP path through it would return one locality for a ZIP
    that covers three, so the ZIP path does not use the locator at all."""
    env = await resolve_location(cw_ctx, zip_code="24450")
    assert "geocode" not in env.data
    assert {s.source_id for s in env.provenance} == {"va-vgin-address-points"}


@pytest.mark.parametrize("kwargs,fragment", [
    ({}, "exactly one"),
    ({"address": "x", "zip_code": "22180"}, "exactly one"),
    ({"zip_code": "2218"}, "5-digit"),
    ({"zip_code": "22180-1234"}, "ZIP+4"),
])
async def test_bad_inputs_are_refused_by_name(cw_ctx, kwargs, fragment):
    with pytest.raises(InvalidQuery) as err:
        await resolve_location(cw_ctx, **kwargs)
    assert fragment in str(err.value)
