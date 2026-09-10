"""Meetings contract tier: the envelope a meetings answer carries, and the
three empties it must never confuse (GitHub issue #13).

A locality with no registered agenda source, a registered locality whose
window holds no meetings, and a jurisdiction string that names no
Virginia government are three different answers. Conflating any two of
them is this tool's signature failure, so each one is pinned here.
"""
import json

import jsonschema
from mcp.client import Client

from commonwealth.servers.build import build_server
from tests.conftest import build_ctx

# The windows the fixtures were recorded over
# (cli.__main__.MEETING_SAMPLE_WINDOWS). A test asking for anything else
# fails the replay loudly rather than passing over invented data.
BUSY = {"start_date": "2026-09-01", "end_date": "2026-09-30"}
EMPTY = {"start_date": "2030-01-01", "end_date": "2030-01-31"}
CANCELLED = {"start_date": "2019-12-01", "end_date": "2019-12-31"}


def _server():
    return build_server(build_ctx(), profile="all")


async def test_search_meetings_has_output_schema():
    server = _server()
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert "civic.search_meetings" in tools
    assert tools["civic.search_meetings"].output_schema is not None


async def test_full_envelope_validates_against_committed_schema(project_root):
    server = _server()
    async with Client(server) as client:
        res = await client.call_tool(
            "civic.search_meetings",
            {"jurisdiction": "Richmond City", **BUSY})
    assert res.is_error is False
    wire = res.structured_content
    committed = json.loads(
        (project_root / "schemas" / "envelope.schema.json").read_text())
    jsonschema.validate(wire, committed)
    assert wire["coverage"]["result"] == "hit"
    assert wire["coverage"]["registry"] == "covered"


async def test_every_record_carries_the_publishers_own_fields():
    ctx = build_ctx()
    from commonwealth.domains.civic import search_meetings

    env = await search_meetings(ctx, "Richmond City", **BUSY)
    records = env.data["results"][0]["records"]
    assert records, "the recorded busy window has meetings in it"
    for r in records:
        assert r["body"] and r["date"] and r["time"]
        # The zone is declared by the manifest, because the payload has
        # none. A record that omitted it would be a wall-clock time with
        # nothing to say where.
        assert r["time_zone"] == "America/New_York"
        assert r["evidence_refs"], "every record cites its evidence"


async def test_a_registry_gap_is_not_an_empty_calendar():
    """Fairfax County holds meetings. This project cannot read them."""
    ctx = build_ctx()
    from commonwealth.domains.civic import search_meetings

    env = await search_meetings(ctx, "Fairfax County", **BUSY)
    assert env.coverage.registry.value == "none"
    assert env.data["results"] == [], "no source answered, so no block"
    assert [g.jurisdiction for g in env.coverage.jurisdictions_unavailable]
    # And the escalation hint, so a model meeting the gap is pointed at
    # the registry rather than left to conclude the county does not meet.
    assert [a.suggested_capability for a in env.next_actions] == [
        "registry.search_sources"]


async def test_a_covered_locality_with_no_meetings_is_a_clean_empty():
    """The other empty: registry covered, publisher answered, none in
    range. Distinguishable from the gap above by every dimension that
    matters."""
    ctx = build_ctx()
    from commonwealth.domains.civic import search_meetings

    env = await search_meetings(ctx, "Richmond City", **EMPTY)
    assert env.coverage.registry.value == "covered"
    assert env.coverage.execution.value == "complete"
    assert env.coverage.result.value == "empty"
    block = env.data["results"][0]
    assert block["record_count"] == 0
    assert "not an absence of coverage" in block["note"]


async def test_the_two_empties_differ_on_the_registry_dimension():
    """The pair, asserted together — the confusion is between them, and a
    test of each alone would not catch them converging."""
    ctx = build_ctx()
    from commonwealth.domains.civic import search_meetings

    gap = await search_meetings(ctx, "Fairfax County", **BUSY)
    empty = await search_meetings(ctx, "Richmond City", **EMPTY)
    assert gap.coverage.result.value == empty.coverage.result.value == "empty"
    assert gap.coverage.registry.value != empty.coverage.registry.value


async def test_an_unknown_jurisdiction_is_neither_of_those():
    ctx = build_ctx()
    from commonwealth.domains.civic import search_meetings

    env = await search_meetings(ctx, "Atlantis", **BUSY)
    assert env.data["results"] == []
    assert "matches no Virginia jurisdiction" in env.data["note"]


async def test_one_adapter_two_localities_differing_only_by_client():
    """The claim the adapter makes, tested rather than asserted in prose.

    Two localities, two manifests, one adapter and no locality-specific
    code — so both answer, and each answer names its own source.
    """
    ctx = build_ctx()
    from commonwealth.domains.civic import search_meetings

    richmond = await search_meetings(ctx, "Richmond City", **BUSY)
    alexandria = await search_meetings(ctx, "Alexandria City", **BUSY)
    assert richmond.data["results"][0]["source_id"] == "va-richmond-city-meetings"
    assert alexandria.data["results"][0]["source_id"] == "va-alexandria-city-meetings"
    assert richmond.data["results"][0]["record_count"] > 0
    assert alexandria.data["results"][0]["record_count"] > 0
    # And the URLs differ only in the client segment.
    r_url = richmond.data["results"][0]["source_url"]
    a_url = alexandria.data["results"][0]["source_url"]
    assert r_url.replace("richmondva", "X") == a_url.replace("alexandria", "X")


async def test_a_cancelled_meeting_is_returned_not_omitted():
    """An omitted cancellation reads as a meeting that will happen."""
    ctx = build_ctx()
    from commonwealth.domains.civic import search_meetings

    env = await search_meetings(ctx, "Richmond City", **CANCELLED)
    records = env.data["results"][0]["records"]
    cancelled = [r for r in records if "cancellation_note" in r]
    assert cancelled, "the recorded window contains cancelled meetings"
    for r in cancelled:
        # The publisher's own words are returned, so the reading can be
        # checked against them.
        assert "cancel" in r["comment"].lower()
        assert "from the comment" in r["cancellation_note"]
        # And the platform's status field is left exactly as published:
        # promoting a prose reading into it would invent a publisher
        # statement that does not exist.
        assert r["agenda_status"] in ("Final", "Final-revised")


async def test_the_cancellation_reading_is_disclosed_as_a_warning():
    ctx = build_ctx()
    from commonwealth.domains.civic import search_meetings

    env = await search_meetings(ctx, "Richmond City", **CANCELLED)
    codes = [w.code.value for w in env.warnings]
    assert "screening_only" in codes
