"""Known answers from the dated publisher recordings."""
from commonwealth.domains.geo import find_zoning
from commonwealth.domains.records import (find_flood_zones, find_permit_outfalls, get_bill,
                                           get_bill_votes, get_election_results)
from commonwealth.fixtures import replay_context


async def test_bill_to_floor_vote_and_later_members():
    ctx = replay_context(["va-lis-session-files"])
    bill = (await get_bill(ctx, "20251", "HB1600")).data["results"][0]["records"][0]
    assert bill["patron"] == "Torian" and bill["text_versions"][0]["document"] == "HB1600"
    history = list(bill["history"])
    offset = bill["next_history_offset"]
    while offset is not None:
        page = (await get_bill(ctx, "20251", "HB1600", offset)).data["results"][0]["records"][0]
        history.extend(page["history"])
        offset = page["next_history_offset"]
    assert len(history) == bill["history_count"]
    ref = next(a["History_refid"] for a in history if "79-Y 18-N" in a["History_description"]
               and a["History_refid"] == "2518627")
    members = []
    offset = 0
    while offset is not None:
        env = await get_bill_votes(ctx, "20251", "HB1600", ref, offset)
        page = env.data["results"][0]
        assert all(e.locator.endswith("VOTE.CSV") for e in env.evidence)
        members.extend(page["records"])
        offset = page["next_offset"]
    assert len({m["member_id"] for m in members}) == len(members) == 100
    assert sum(m["vote"] == "Y" for m in members) == 79
    assert sum(m["vote"] == "N" for m in members) == 18


async def test_election_totals_are_not_summed_with_candidates():
    ctx = replay_context(["va-historical-election-results"])
    env = await get_election_results(ctx, "2021-11-02", "Governor", "Accomack County")
    rows = env.data["results"][0]["records"]
    assert len(rows) == 6 and all(r["division_type"] == "Locality" and not r["vote_channel"] for r in rows)
    votes = {r["candidate_name"]: r["votes"] for r in rows}
    assert votes["Glenn Allen Youngkin"] == "7878" and votes["Total Votes Cast"] == "12897"


async def test_maps_and_parcel_evidence():
    ctx = replay_context()
    zoning = await find_zoning(ctx, jurisdiction="Norfolk City", lon=-76.2859, lat=36.8508)
    assert "HC-EF" in {r["district"] for b in zoning.data["results"] for r in b["records"]}
    flood = await find_flood_zones(ctx, "Norfolk City", lon=-76.295, lat=36.85)
    zones, panels = flood.data["results"]
    assert zones["records"][0]["zone"] == "AE"
    panel = panels["records"][0]
    assert panel["panel"] == "5101040056H" and panel["effective_date"].startswith("2017-02-17")
    flood = await find_flood_zones(ctx, "Richmond City", pin="E0000720034")
    blocks = flood.data["results"]
    assert len(blocks) == 4 and len({b["parcel_evidence_ref"] for b in blocks}) == 2
    assert all(b["parcel_evidence_ref"] in r["evidence_refs"] for b in blocks for r in b["records"])
    permits = await find_permit_outfalls(ctx, "Richmond City", -77.436, 37.5407)
    rows = permits.data["results"][0]["records"]
    assert len(rows) == 7 and any(r["permit"] == "VA0063177" and r["facility"] == "Richmond WWTP" for r in rows)
