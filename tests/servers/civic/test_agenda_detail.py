"""A meeting, an agenda entry and a vote each have their own source identity."""
import json

import pytest
from mcp.client import Client

from commonwealth.adapters.agenda_platform import _utc
from commonwealth.core.errors import InvalidQuery, SourceUnavailable
from commonwealth.core.registry import OperationalState
from commonwealth.domains.civic import get_item_votes, get_meeting_agenda, search_meetings
from commonwealth.fixtures import FIXTURES_DIR
from commonwealth.servers.build import build_server
from tests.conftest import build_ctx

RICHMOND = "va-richmond-city-meetings"
ALEXANDRIA = "va-alexandria-city-meetings"


async def test_follow_published_ids_from_a_notice_to_votes_through_mcp():
    async with Client(build_server(build_ctx(), "civic")) as client:
        async def call(name, **args):
            result = await client.call_tool("civic." + name, args)
            assert not result.is_error, result.content
            return result.structured_content

        calendar = await call("search_meetings", jurisdiction="Richmond City",
                              start_date="2026-09-01", end_date="2026-09-01",
                              body="Planning Commission")
        block = calendar["data"]["results"][0]
        meeting, = block["records"]
        agenda = await call("get_meeting_agenda", source_id=block["source_id"],
                            event_id=meeting["event_id"])
        first = agenda["data"]["results"][0]
        assert agenda["coverage"]["pagination"] == "truncated"
        second = await call("get_meeting_agenda", **first["next"])
        last = second["data"]["results"][0]
        assert last["next"] is None
        assert not ({r["item_id"] for r in first["records"]}
                    & {r["item_id"] for r in last["records"]})
        minutes = next(r for r in first["records"] if r["matter_file"] == "PDRMIN 2026.016")
        votes = await call("get_item_votes", source_id=first["source_id"], item_id=minutes["item_id"])
        rows = votes["data"]["results"][0]["records"]
        assert ("Burchell Pinnock", "Aye") in {(r["person"], r["vote"]) for r in rows}
        assert {ref for r in rows for ref in r["evidence_refs"]} == {
            e["id"] for e in votes["evidence"]}
        assert votes["_execution"]["server"] == "commonwealth-civic"
        ordinance = next(r for r in last["records"] if r["matter_file"] == "ORD. 2026-093")
        assert ordinance["action"].strip() == "recommended for continuance"
        other = await call("get_item_votes", source_id=last["source_id"], item_id=ordinance["item_id"])
        assert other["coverage"]["result"] == "empty"
        assert other["coverage"]["execution"] == "complete"
        assert other["provenance"][0]["source_id"] == RICHMOND


async def test_alexandrias_item_and_source_travel_together(cw_ctx):
    env = await get_meeting_agenda(cw_ctx, ALEXANDRIA, "2757")
    block, = env.data["results"]
    assert env.provenance[0].jurisdiction == "va:alexandria-city"
    assert block["source_url"].endswith("/alexandria/events/2757/eventitems")
    # A complete brief can follow every continuation, even for this longer agenda.
    item_ids = [r["item_id"] for r in block["records"]]
    next_page = block["next"]
    while next_page:
        following = await get_meeting_agenda(cw_ctx, **next_page)
        page = following.data["results"][0]
        item_ids.extend(r["item_id"] for r in page["records"])
        next_page = page["next"]
    fixture = json.loads((FIXTURES_DIR / ALEXANDRIA / "recorded.json").read_text())
    assert len(set(item_ids)) == len(item_ids) == fixture["summary"]["agenda_items"]
    row = next(r for r in block["records"] if r["matter_file"] == "27-1208")
    votes = await get_item_votes(cw_ctx, block["source_id"], row["item_id"])
    assert votes.coverage.registry.value == "covered"
    assert votes.coverage.result.value == "empty"


class RefusingFetcher:
    async def fetch_json_list(self, url, params):
        raise AssertionError("this input must not make a request")


async def test_source_identity_is_not_a_url_or_a_fallback_to_another_calendar():
    ctx = build_ctx(agenda_fetcher=RefusingFetcher())
    for sid in ("https://webapi.legistar.com/v1/richmondva", "va-vgin-parcels"):
        with pytest.raises(InvalidQuery):
            await get_meeting_agenda(ctx, sid, "5144")
    for record_id in ("../votes", "-1", "0", "5?other=1", "１２３"):
        with pytest.raises(InvalidQuery):
            await get_meeting_agenda(ctx, RICHMOND, record_id)
    with pytest.raises(InvalidQuery):
        await get_item_votes(ctx, RICHMOND, "268162", offset=-1)
    gap = await get_meeting_agenda(ctx, "va-hampton-city-meetings", "5144")
    assert gap.coverage.registry.value == "none"
    ctx.sources.set_operational(RICHMOND, OperationalState.unavailable)
    down = await get_meeting_agenda(ctx, RICHMOND, "5144")
    assert down.coverage.jurisdictions_unavailable[0].reason == "source_unavailable"


@pytest.mark.parametrize("failure", ["outage", "cross_event", "missing_item_id"])
async def test_an_unusable_agenda_page_never_becomes_a_clean_empty(failure):
    class Fetcher:
        async def fetch_json_list(self, url, params):
            if failure == "outage":
                raise SourceUnavailable("server unavailable")
            return [{"EventItemEventId": 999, "EventItemId": 1}
                    if failure == "cross_event" else {"EventItemEventId": 5144}]

    env = await get_meeting_agenda(build_ctx(agenda_fetcher=Fetcher()), RICHMOND, "5144")
    assert env.coverage.execution.value == "failed"
    assert env.coverage.pagination.value == "unknown"
    assert env.coverage.source_failures[0].source_id == RICHMOND
    assert not env.data["results"]


async def test_calendar_page_cap_is_detected_before_body_filtering():
    recorded = json.loads((FIXTURES_DIR / RICHMOND / "recorded.json").read_text())
    row = recorded["exchanges"][0]["response"][0]

    class CappedFetcher:
        async def fetch_json_list(self, url, params):
            return [row] * 1000

    env = await search_meetings(build_ctx(agenda_fetcher=CappedFetcher()), "Richmond City",
                                "2026-09-01", "2026-09-30", body="Missing body")
    assert env.coverage.result.value == "empty"
    assert env.coverage.pagination.value == "truncated"
    assert "narrow the dates" in env.data["results"][0]["note"]


def test_utc_normalizes_offsets_and_refuses_a_date_without_time():
    assert _utc("2026-11-03T23:00:00-05:00") == "2026-11-04T04:00:00Z"
    assert _utc("2026-11-03") is None


def test_calendar_health_cannot_confirm_absence_beyond_the_publisher_limit():
    from commonwealth.cli.__main__ import _meeting_health_line

    sample = json.loads((FIXTURES_DIR / RICHMOND / "recorded.json").read_text())
    row = next(r for r in sample["exchanges"][0]["response"]
               if r["EventBodyName"] == "Planning Commission")

    class CappedFetcher:
        async def fetch_json_list(self, url, params):
            return [row] * 1000

    ctx = build_ctx(agenda_fetcher=CappedFetcher())
    line, ok = _meeting_health_line(ctx, ctx.sources.get(RICHMOND))
    assert not ok and "unknown beyond the page limit" in line
    assert "ABSENT" not in line


def test_a_malformed_client_is_refused_at_manifest_load(tmp_path):
    import shutil

    from commonwealth.core.registry import SourceRegistry
    from commonwealth.runtime import SOURCES_DIR

    root = tmp_path / "sources"
    shutil.copytree(SOURCES_DIR, root)
    manifest = root / "local" / "richmond-city" / "meetings.yaml"
    manifest.write_text(manifest.read_text().replace("client: richmondva", "client: ../alexandria"))
    with pytest.raises(ValueError, match="client"):
        SourceRegistry.load(root)
