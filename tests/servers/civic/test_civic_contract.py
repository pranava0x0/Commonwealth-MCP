"""Civic contract tier: envelope validity and coverage honesty through the
in-memory MCP client, so the whole wire path is what's tested."""
import json

import jsonschema
from mcp.client import Client

from commonwealth.servers.build import build_server
from tests.conftest import build_ctx


def _server():
    return build_server(build_ctx(), profile="all")


async def test_get_code_section_has_output_schema():
    server = _server()
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert "civic.get_code_section" in tools
    assert tools["civic.get_code_section"].output_schema is not None


async def test_full_envelope_validates_against_committed_schema(project_root):
    server = _server()
    async with Client(server) as client:
        res = await client.call_tool("civic.get_code_section",
                                     {"citation": "1-500"})
    assert res.is_error is False
    wire = res.structured_content
    committed = json.loads(
        (project_root / "schemas" / "envelope.schema.json").read_text())
    jsonschema.validate(wire, committed)
    assert wire["coverage"]["result"] == "hit"


async def test_missing_section_coverage_shape():
    server = _server()
    async with Client(server) as client:
        res = await client.call_tool("civic.get_code_section",
                                     {"citation": "1-999999"})
    wire = res.structured_content
    assert wire["coverage"]["result"] == "empty"
    assert wire["coverage"]["registry"] == "covered", (
        "the source exists and answered — a clean miss, not a gap"
    )


async def test_browse_code_has_output_schema():
    server = _server()
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert "civic.browse_code" in tools
    assert tools["civic.browse_code"].output_schema, (
        "a tool with no output schema is a tool a client cannot type-check")


async def test_browse_code_is_out_of_the_default_profile_and_in_discovery():
    """Decision 0002's budget. `default` sits at nine against a ceiling of
    twelve, and issue #11's two legislative tools have first claim on the
    room, so the Code walk goes to `discovery` — where it belongs anyway,
    since reaching a citation you do not have is a discovery act."""
    from commonwealth.core.toolreg import (PROFILE_DEFAULT_CEILING,
                                           PROFILE_HARD_CEILING,
                                           expand_profile)
    from commonwealth.servers.build import registries

    regs = registries()
    names = {p: {t.name for t in expand_profile(p, regs)}
             for p in ("default", "discovery", "all")}
    assert "civic.browse_code" not in names["default"]
    assert "civic.browse_code" in names["discovery"]
    assert "civic.get_code_section" in names["default"], (
        "the citation lookup stays in default; only the walk moved out")
    assert len(names["default"]) + 2 <= PROFILE_DEFAULT_CEILING, (
        "issue #11 adds two legislative tools to default; this leaves "
        "room for them")
    assert len(names["all"]) <= PROFILE_HARD_CEILING


async def test_a_browse_walk_ends_at_a_citation_the_other_tool_reads():
    """The two civic tools are meant to compose: walk to a section, then
    read it. If the walk's `cite_with` did not fit `get_code_section`'s
    argument, the pair would only look joined up."""
    server = _server()
    async with Client(server) as client:
        walked = await client.call_tool("civic.browse_code",
                                        {"title": "15.2", "chapter": "22"})
        rows = walked.structured_content["data"]["results"][0]["records"]
        cite = next(r["cite_with"] for r in rows if r["number"] == "15.2-2200")
        read = await client.call_tool("civic.get_code_section", cite)
    assert not read.is_error, read.content
    blk = read.structured_content["data"]["results"][0]
    assert blk["found"] is True, (
        "the citation the walk handed over did not resolve")
    assert blk["citation"] == "15.2-2200"
    assert blk["paragraphs"], "the section came back with no text"
