"""geo.find_landmarks over VGIN's landmark layer (GitHub issue #7).

The layer is small and unusually quirk-prone: a layer id that is not 0, a
per-record verification date that is often null, and records that are
somebody else's — DOE's for a school, USPS's for a post office.
"""
import pytest
import yaml

from commonwealth.core.errors import InvalidQuery
from commonwealth.domains.geo import find_landmarks
from commonwealth.runtime import SOURCES_DIR

MANIFEST = SOURCES_DIR / "state" / "vgin-landmarks.yaml"


def test_the_registered_layer_id_is_one_not_zero():
    """Layer 0 does not exist on this service; it answers HTTP 500 with
    `{"error":{"code":500,"message":"json"}}`. A layer_id copied from the
    parcels manifest would fail at the first query, and this is the
    assertion that stops that passing review."""
    doc = yaml.safe_load(MANIFEST.read_text())
    assert doc["adapter"]["layers"]["landmarks"]["layer_id"] == 1


async def test_by_point_with_a_radius(cw_ctx):
    env = await find_landmarks(cw_ctx, jurisdiction="Vienna",
                               lon=-77.2653, lat=38.9012)
    block = env.data["results"][0]
    assert block["record_count"] == 4
    names = {r["name"] for r in block["records"]}
    assert "Vienna Elementary School" in names


async def test_by_name_prefix(cw_ctx):
    env = await find_landmarks(cw_ctx, jurisdiction="Fairfax County",
                               name="Vienna")
    assert env.data["results"][0]["record_count"] == 5


async def test_by_place_type(cw_ctx):
    env = await find_landmarks(cw_ctx, jurisdiction="Fairfax County",
                               place_type="Public Library Points")
    assert env.data["results"][0]["record_count"] == 23


async def test_each_record_names_the_organisation_it_came_from(cw_ctx):
    """The publisher is an aggregator here. A school's address is the
    Department of Education's record, not the map publisher's, and the
    envelope has to say so rather than implying otherwise."""
    env = await find_landmarks(cw_ctx, jurisdiction="Vienna",
                               lon=-77.2653, lat=38.9012)
    rows = env.data["results"][0]["records"]
    assert {r["source_organization"] for r in rows} == {
        "DCJS", "Agency", "DOE", "USPS"}
    school = next(r for r in rows if r["source_organization"] == "DOE")
    assert "DOE" in school["authority_note"]
    assert "not from the layer's publisher" in school["authority_note"]


async def test_a_null_verification_date_says_so_rather_than_inheriting_one(
        cw_ctx):
    """One of the four Vienna records has no LastCheck. Falling back to
    the layer's date would claim a verification that never happened."""
    env = await find_landmarks(cw_ctx, jurisdiction="Vienna",
                               lon=-77.2653, lat=38.9012)
    rows = env.data["results"][0]["records"]
    unchecked = [r for r in rows if r["record_checked_at"] is None]
    assert len(unchecked) == 1
    assert "not the same as verified recently" in \
        unchecked[0]["record_checked_note"]
    checked = [r for r in rows if r["record_checked_at"] is not None]
    assert checked and all(r["record_checked_at"].endswith("Z")
                           for r in checked)


async def test_record_urls_are_data_and_are_never_fetched(cw_ctx):
    """The egress allowlist is per manifest, so following a link found
    inside a record would drive straight through it."""
    env = await find_landmarks(cw_ctx, jurisdiction="Vienna",
                               lon=-77.2653, lat=38.9012)
    rows = env.data["results"][0]["records"]
    with_urls = [r for r in rows if r.get("url")]
    assert with_urls, "the recorded set has URLs; the assertion needs them"
    for row in with_urls:
        assert "Nothing in Commonwealth fetches" in row["url_note"]
    # The replay fetcher records every URL asked for. None of the record
    # URLs may appear there.
    asked = " ".join(cw_ctx.arcgis._fetcher.calls)
    for row in with_urls:
        assert row["url"] not in asked


async def test_the_postal_city_is_not_the_jurisdiction(cw_ctx):
    env = await find_landmarks(cw_ctx, jurisdiction="Vienna",
                               lon=-77.2653, lat=38.9012)
    row = env.data["results"][0]["records"][0]
    assert row["locality"] == "Fairfax County"
    assert "postal city, not the government" in row["authority_note"]


async def test_absence_is_never_reported_as_a_place_not_existing(cw_ctx):
    env = await find_landmarks(cw_ctx, jurisdiction="Vienna",
                               lon=-77.2653, lat=38.9012)
    warning = next(w for w in env.warnings
                   if w.code.value == "screening_only")
    assert "not an inventory" in warning.message


async def test_an_unfiltered_query_is_refused(cw_ctx):
    with pytest.raises(InvalidQuery) as err:
        await find_landmarks(cw_ctx, jurisdiction="Fairfax County")
    assert "at least one" in str(err.value)
