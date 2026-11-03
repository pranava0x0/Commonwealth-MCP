from commonwealth.domains.records import find_flood_zones, get_bill_votes, search_purchases
from commonwealth.fixtures import replay_context


async def test_unlinked_vote_never_uses_other_bills_ballots():
    ctx = replay_context(["va-lis-session-files"])
    files = ctx.public_records.fetcher.downloads
    del files[next(u for u in files if u.endswith("VOTE.CSV"))]
    result = await get_bill_votes(ctx, "20251", "HB123", "H02V2512236")
    assert result.coverage.execution.value == "complete" and result.data["results"][0]["records"] == []


async def test_html_vote_export_is_a_source_failure():
    ctx = replay_context(["va-lis-session-files"])
    files = ctx.public_records.fetcher.downloads
    files[next(u for u in files if u.endswith("VOTE.CSV"))] = "<html>temporarily unavailable</html>"
    result = await get_bill_votes(ctx, "20251", "HB1600", "H02V2512236")
    assert result.coverage.execution.value == "failed"
    assert result.coverage.source_failures[0].error == "SourceSchemaChanged"


async def test_ckan_failure_is_not_empty_coverage(monkeypatch):
    ctx = replay_context([])
    async def failed(url, params):
        return {"success": False, "result": {"records": []}}
    monkeypatch.setattr(ctx.public_records.fetcher, "fetch_json", failed)
    result = await search_purchases(ctx, order="abc")
    assert result.coverage.execution.value == "failed" and not result.data["results"]


async def test_unmapped_point_is_not_a_risk_grade():
    result = await find_flood_zones(replay_context(), "Norfolk City", -74.5, 36.5)
    assert len(result.data["results"]) == 2
    assert all(not b["records"] for b in result.data["results"])
    assert "does not establish low risk" in result.data["note"]


async def test_parcel_prerequisite_gap_is_not_a_completed_flood_search():
    result = await find_flood_zones(replay_context(), "Fairfax County", pin="NO SUCH PIN")
    assert result.coverage.execution.value == "partial" and result.coverage.pagination.value == "unknown"
    assert not result.data["results"] and "not queried" in result.data["note"]
