"""Contributor search reads one CKAN page; none of its resource URLs are fetched."""
import pytest

from commonwealth.adapters.replay import ReplayFetcher
from commonwealth.cli.discover import PORTAL, discover
from commonwealth.core.errors import InvalidQuery, SourceSchemaChanged, SourceUnavailable, TermsRestricted
from commonwealth.core.registry import AutomationStatus


def portal(response, rows=4, start=0):
    return ReplayFetcher([{"url": PORTAL, "params": {"q": "zoning", "rows": rows, "start": start},
                           "response": response}])


def dataset(org, title, *urls):
    return {"title": title, "organization": {"title": org}, "metadata_modified": "2026-06-12",
            "resources": [{"url": u} for u in urls]}


async def test_discovery_distinguishes_local_gaps_registered_sources_and_catalog_links(cw_ctx):
    # Publisher labels and first two service URLs checked on 2026-11-03;
    # mixed-resource and ambiguous-publisher cases exercise the parser.
    prefix = "https://gis.winchesterva.gov/arcgis/rest/services/Winchester/Zoning/MapServer/0"
    pw = "https://gisweb.pwcva.gov/arcgis/rest/services/OpenData/OpenData/MapServer/21"
    page = [dataset("Winchester", "Zoning", prefix),
            dataset("City of Norfolk - GIS Portal", "Zoning", "https://example.org/norfolk"),
            dataset("Prince William County", "Zoning", "https://example.org/pwc", pw, pw),
            dataset("Fairfax", "Zoning", "https://example.org/fairfax")]
    fetcher = portal({"success": True, "result": {"count": 20, "results": page}}, start=4)
    result = await discover(cw_ctx, "zoning", 4, 4, fetcher)
    assert len(fetcher.calls) == 1
    assert result["next_start"] == 8 and result["datasets_examined"] == 4
    assert [(c["jurisdiction"], c["local_coverage"], c["kind"]) for c in result["candidates"]] == [
        ("va:prince-william-county", "local_gap", "layer"), ("va:norfolk-city", "local_gap", "link"),
        ("va:winchester-city", "local_source", "layer"), (None, "unassessed", "link")]
    assert result["candidates"][0]["resource_url"] == pw


async def test_portal_empty_and_failed_responses_are_different(cw_ctx):
    empty = await discover(cw_ctx, "zoning", 4, fetcher=portal(
        {"success": True, "result": {"count": 0, "results": []}}))
    assert empty == {"total_datasets": 0, "datasets_examined": 0, "next_start": None, "candidates": []}
    for payload, error in [({"success": False}, SourceUnavailable),
                           ({"success": True, "result": {"count": 2, "results": {}}}, SourceSchemaChanged)]:
        with pytest.raises(error):
            await discover(cw_ctx, "zoning", 4, fetcher=portal(payload))


@pytest.mark.parametrize("query,limit,start", [("", 20, 0), ("parcel", 51, 0), ("parcel", 20, -1)])
async def test_invalid_search_refused_before_network(cw_ctx, query, limit, start):
    with pytest.raises(InvalidQuery):
        await discover(cw_ctx, query, limit, start)


async def test_portal_access_change_stops_the_request(cw_ctx):
    manifest = cw_ctx.sources.get("va-open-data-portal")
    manifest.access.automation_status = AutomationStatus.do_not_automate
    fetcher = portal({"success": False})
    with pytest.raises(TermsRestricted):
        await discover(cw_ctx, "zoning", 4, fetcher=fetcher)
    assert not fetcher.calls


async def test_non_web_and_credential_urls_are_not_offered_as_candidates(cw_ctx):
    row = dataset("Virginia", "reference", "file:///tmp/x", "javascript:alert(1)",
                  "https://user:password@example.org/FeatureServer/0",
                  "https://example.org/path\nother", "https://example.org/download.zip")
    result = await discover(cw_ctx, "zoning", 4, fetcher=portal(
        {"success": True, "result": {"count": 1, "results": [row]}}))
    candidate, = result["candidates"]
    assert candidate["resource_url"] == "https://example.org/download.zip"
    assert candidate["local_coverage"] == "unassessed" and result["next_start"] is None
