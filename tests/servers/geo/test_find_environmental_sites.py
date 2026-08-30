"""geo.find_environmental_sites over DEQ (GitHub issue #8).

Two firsts: the first publisher that is neither VGIN nor a locality, and
the first MapServer rather than a FeatureServer. And the registry's
highest-disclosure source — an environmental answer read as broader than
it is sends someone to the wrong conclusion about a property.
"""
import pytest
import yaml

from commonwealth.core.errors import InvalidQuery
from commonwealth.domains.geo import find_environmental_sites
from commonwealth.runtime import SOURCES_DIR

MANIFEST = SOURCES_DIR / "state" / "deq-environmental-sites.yaml"


async def test_a_mapserver_answers_through_the_featureserver_adapter(cw_ctx):
    """The adapter was written against FeatureServer and had never been
    pointed at a MapServer. This asserts that it works rather than
    leaving "it happened to work in one probe" as the finding."""
    env = await find_environmental_sites(cw_ctx,
                                         jurisdiction="Richmond City",
                                         lon=-77.4360, lat=37.5407)
    block = env.data["results"][0]
    assert block["record_count"] == 17
    assert "MapServer" in cw_ctx.sources.get(
        "va-deq-water-quality-stations").adapter.model_dump()["service_url"]


async def test_the_disclaimer_rides_on_a_hit(cw_ctx):
    env = await find_environmental_sites(cw_ctx,
                                         jurisdiction="Richmond City",
                                         lon=-77.4360, lat=37.5407)
    warning = next(w for w in env.warnings
                   if w.code.value == "screening_only")
    assert "NOT a complete inventory" in warning.message
    assert "NOT a determination" in warning.message


async def test_the_disclaimer_rides_on_an_empty_result_too(cw_ctx):
    """The empty answer is the one most likely to be read as "nothing
    here", which is exactly what it does not mean."""
    env = await find_environmental_sites(cw_ctx, jurisdiction="Virginia",
                                         lon=-74.5, lat=36.5)
    assert env.coverage.result.value == "empty"
    assert env.coverage.execution.value == "complete", (
        "the source answered; 'failed' would confuse a gap with an outage")
    warning = next(w for w in env.warnings
                   if w.code.value == "screening_only")
    assert "no monitoring station of that kind is on record" in \
        warning.message


async def test_each_station_says_what_it_is_and_is_not(cw_ctx):
    env = await find_environmental_sites(cw_ctx,
                                         jurisdiction="Richmond City",
                                         lon=-77.4360, lat=37.5407)
    row = env.data["results"][0]["records"][0]
    assert "says nothing about what was found" in row["record_note"]
    assert row["last_sample_date"] is None or \
        row["last_sample_date"].endswith("Z")


async def test_a_recorded_terms_gap_becomes_a_warning_on_every_answer(
        cw_ctx):
    """DEQ's own terms pages return an Akamai 403 to a plain request and
    none of its 97 open-data datasets carries a license. That gap is
    recorded in the manifest and it has to reach the caller, not just a
    contributor reading YAML."""
    doc = yaml.safe_load(MANIFEST.read_text())
    assert doc["access"]["terms_gap"], "the manifest records the gap"
    env = await find_environmental_sites(cw_ctx,
                                         jurisdiction="Richmond City",
                                         lon=-77.4360, lat=37.5407)
    warning = next(w for w in env.warnings if w.code.value == "terms_note")
    assert warning.source_id == "va-deq-water-quality-stations"
    assert "not a licence" in warning.message


async def test_a_source_with_no_terms_gap_raises_no_terms_warning(cw_ctx):
    """The mechanism has to stay quiet where the review came back clean,
    or it becomes noise everyone learns to ignore."""
    from commonwealth.domains.geo import find_parcel
    env = await find_parcel(cw_ctx, jurisdiction="Charles City County",
                            pin="7-4-B-2")
    assert not [w for w in env.warnings if w.code.value == "terms_note"]


async def test_the_search_says_it_is_geographic_not_jurisdictional(cw_ctx):
    """The layer is organised by watershed and DEQ region, with no
    locality field at all, so a result can sit in a neighbouring
    jurisdiction."""
    env = await find_environmental_sites(cw_ctx,
                                         jurisdiction="Richmond City",
                                         lon=-77.4360, lat=37.5407)
    note = env.data["results"][0]["search_note"]
    assert "no locality field" in note
    scope = cw_ctx.arcgis.jurisdiction_scope(
        cw_ctx.sources.get("va-deq-water-quality-stations"), "stations")
    assert scope.mode == "none"


async def test_a_jurisdiction_only_query_is_refused(cw_ctx):
    with pytest.raises(InvalidQuery) as err:
        await find_environmental_sites(cw_ctx,
                                       jurisdiction="Richmond City")
    assert "organised by watershed" in str(err.value)
