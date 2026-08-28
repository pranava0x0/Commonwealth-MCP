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
