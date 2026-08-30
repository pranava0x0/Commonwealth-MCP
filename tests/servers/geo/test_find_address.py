"""geo.find_address over VGIN's address points (GitHub issue #4).

The interesting assertions are about what the fields mean rather than
whether the query runs: the issue that specified this source described
PLACENAME as a postal place, and the live layer says otherwise.
"""
import pytest

from commonwealth.core.errors import InvalidQuery
from commonwealth.domains.geo import find_address


async def test_by_address_prefix_within_a_jurisdiction(cw_ctx):
    env = await find_address(cw_ctx, jurisdiction="Fairfax County",
                             address="4501 Carlby Ln")
    block = env.data["results"][0]
    assert block["record_count"] == 1
    assert block["records"][0]["full_address"].startswith("4501 CARLBY LN")


async def test_the_postal_city_is_never_the_government(cw_ctx):
    """The § 3 case-1 trap in the address layer itself: a Fairfax County
    record whose postal city is an independent city it is not in."""
    env = await find_address(cw_ctx, jurisdiction="Fairfax County",
                             address="4501 Carlby Ln")
    row = env.data["results"][0]["records"][0]
    assert row["po_name"] == "ALEXANDRIA"
    assert row["locality"] == "Fairfax County"
    assert row["fips"] == "51059"
    assert "po_name" in row["place_note"] and "not a government" in \
        row["place_note"]


def test_placename_is_mapped_as_a_landmark_not_a_place():
    """Read live 2026-08-29, PLACENAME holds facility names ("Rose Hill
    Elementary School") and is empty for ordinary addresses. The issue
    that specified this source called it a postal place; mapping it that
    way would have put a school's name where a city belongs."""
    import yaml
    from commonwealth.runtime import SOURCES_DIR
    doc = yaml.safe_load(
        (SOURCES_DIR / "state" / "vgin-address-points.yaml").read_text())
    mapping = doc["adapter"]["layers"]["addresses"]["field_mapping"]
    assert mapping["landmark_name"] == "PLACENAME"
    assert mapping["po_name"] == "PO_NAME"
    assert "place" not in mapping


async def test_by_point_returns_nearby_addresses(cw_ctx):
    """Address points sit on structures, so an exact intersect against a
    coordinate taken from a map click answers 'no address here' for a
    house. The query buffers."""
    env = await find_address(cw_ctx, jurisdiction="Vienna",
                             lon=-77.26436153964, lat=38.90067620715)
    block = env.data["results"][0]
    assert block["record_count"] > 1
    assert any("CENTER ST S" in (r["full_address"] or "")
               for r in block["records"])


async def test_a_screening_warning_rides_with_every_hit(cw_ctx):
    env = await find_address(cw_ctx, jurisdiction="Fairfax County",
                             address="4501 Carlby Ln")
    warning = next(w for w in env.warnings
                   if w.code.value == "screening_only")
    assert "does not exist" in warning.message


async def test_record_vintage_comes_from_the_record(cw_ctx):
    """LASTUPDATE is per record, so a record's age is its own rather than
    the layer's retrieval time."""
    env = await find_address(cw_ctx, jurisdiction="Fairfax County",
                             address="4501 Carlby Ln")
    row = env.data["results"][0]["records"][0]
    assert "last_update" not in row, "the raw epoch should be converted"
    assert row["record_updated_at"] is None or \
        row["record_updated_at"].endswith("Z")


@pytest.mark.parametrize("kwargs,fragment", [
    ({}, "exactly one"),
    ({"address": "x", "lon": 1.0, "lat": 2.0}, "exactly one"),
    ({"lon": 1.0}, "both lon and lat"),
])
async def test_bad_inputs_are_refused_by_name(cw_ctx, kwargs, fragment):
    with pytest.raises(InvalidQuery) as err:
        await find_address(cw_ctx, jurisdiction="Fairfax County", **kwargs)
    assert fragment in str(err.value)
