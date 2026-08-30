"""geo.find_buildings over VGIN's statewide footprints (GitHub issue #6).

Two things carry most of the weight: an area number published in a
projection that inflates it, and a layer where the interesting attribute
fields are usually null.
"""
import pytest

from commonwealth.core.errors import InvalidQuery
from commonwealth.domains.geo import (_web_mercator_area_to_ground,
                                      find_buildings)


async def test_by_point_returns_nearby_footprints(cw_ctx):
    env = await find_buildings(cw_ctx, jurisdiction="Vienna",
                               lon=-77.26436153964, lat=38.90067620715)
    block = env.data["results"][0]
    assert block["record_count"] >= 1
    assert all("footprint_area_web_mercator_sq_m" in r
               for r in block["records"])


async def test_by_parcel_pin_composes_with_the_parcel_sources(cw_ctx):
    """"What is built on this parcel" is a question about a polygon
    somebody else publishes, so the tool asks parcel.lookup for it rather
    than duplicating a parcel layer."""
    env = await find_buildings(cw_ctx, jurisdiction="Richmond City",
                               pin="C0010126019")
    block = env.data["results"][0]
    assert block["record_count"] == 2
    ev = next(e for e in env.evidence
              if e.id == block["records"][0]["evidence_refs"][0])
    assert "parcel_geometry_intersection" in ev.transformations


async def test_area_is_never_returned_as_a_bare_number(cw_ctx):
    """The publisher's Shape__Area is in EPSG:3857, where area is inflated
    by about 1.6x at Virginia's latitudes. Returning it unlabelled would
    hand a caller a wrong ground area that looks right."""
    env = await find_buildings(cw_ctx, jurisdiction="Vienna",
                               lon=-77.26436153964, lat=38.90067620715)
    row = env.data["results"][0]["records"][0]
    raw = row["footprint_area_web_mercator_sq_m"]
    approx = row["footprint_area_sq_m_approx"]
    assert raw > approx, "the projection inflates area; converting shrinks it"
    assert 1.5 < raw / approx < 1.75, (
        f"expected roughly sec^2(38 deg) ~ 1.61x, got {raw / approx}")
    assert "EPSG:3857" in row["area_note"]


def test_the_area_conversion_is_the_web_mercator_scale_factor():
    """A unit check on the conversion itself, so a refactor cannot quietly
    turn it into a no-op."""
    assert _web_mercator_area_to_ground(None, 38.0) is None
    # At the equator Web Mercator is undistorted, so the value is
    # unchanged; at 38 degrees it shrinks by sec squared.
    assert _web_mercator_area_to_ground(1000.0, 0.0) == 1000.0
    assert _web_mercator_area_to_ground(1000.0, 38.0) == pytest.approx(
        620.9, abs=1.0)


async def test_the_conversion_is_declared_in_transformations(cw_ctx):
    env = await find_buildings(cw_ctx, jurisdiction="Vienna",
                               lon=-77.26436153964, lat=38.90067620715)
    ev = next(e for e in env.evidence)
    assert any(t.startswith("area:web_mercator_to_ground")
               for t in ev.transformations), ev.transformations


async def test_publisher_codes_are_decoded_from_the_publishers_own_list(
        cw_ctx):
    """BUILDINGCLASS has a coded-value domain on the layer. The label
    comes from that domain and the raw code stays, because a caller
    checking against the publisher's documentation needs the code."""
    env = await find_buildings(cw_ctx, jurisdiction="Vienna",
                               lon=-77.26436153964, lat=38.90067620715)
    row = env.data["results"][0]["records"][0]
    assert "building_class" in row and "building_class_label" in row
    ev = next(e for e in env.evidence)
    assert any(t.startswith("value_labels:") for t in ev.transformations)


async def test_a_dense_query_truncates_and_says_so(cw_ctx):
    """998 footprints live within 800 m of downtown Richmond, past both
    the inline cap and the page-walk budget."""
    env = await find_buildings(cw_ctx, jurisdiction="Richmond City",
                               lon=-77.4360, lat=37.5407,
                               radius_meters=800.0)
    block = env.data["results"][0]
    assert len(block["records"]) == 25, "the inline cap must hold"
    assert block["record_count"] > 25
    assert env.coverage.pagination.value == "truncated"
    assert any(w.code.value == "truncated_inline" for w in env.warnings)


async def test_a_missing_footprint_is_never_reported_as_vacant_land(cw_ctx):
    env = await find_buildings(cw_ctx, jurisdiction="Vienna",
                               lon=-77.26436153964, lat=38.90067620715)
    warning = next(w for w in env.warnings
                   if w.code.value == "screening_only")
    assert "not evidence of vacant land" in warning.message


async def test_an_unmatched_pin_is_a_parcel_miss_not_unbuilt_ground(cw_ctx):
    env = await find_buildings(cw_ctx, jurisdiction="Richmond City",
                               pin="NO SUCH PIN")
    assert env.data["results"] == []
    assert env.coverage.result.value == "empty"
    assert "not a statement that the ground is unbuilt" in env.data["note"]


@pytest.mark.parametrize("kwargs,fragment", [
    ({}, "exactly one"),
    ({"pin": "x", "lon": 1.0, "lat": 2.0}, "exactly one"),
    ({"lat": 2.0}, "both lon and lat"),
])
async def test_bad_inputs_are_refused_by_name(cw_ctx, kwargs, fragment):
    with pytest.raises(InvalidQuery) as err:
        await find_buildings(cw_ctx, jurisdiction="Vienna", **kwargs)
    assert fragment in str(err.value)
