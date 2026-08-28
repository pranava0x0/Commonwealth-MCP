"""Registry/discovery tools through the in-memory MCP client."""
import json

import jsonschema
from mcp.client import Client

from commonwealth.servers.build import build_server
from tests.conftest import build_ctx


async def _call(tool: str, args: dict) -> dict:
    server = build_server(build_ctx(), profile="all")
    async with Client(server) as client:
        res = await client.call_tool(tool, args)
        assert res.is_error is False, res.content
        return res.structured_content


async def test_resolve_validates_and_carries_execution(project_root):
    wire = await _call("registry.resolve_jurisdiction", {"query": "51059"})
    committed = json.loads(
        (project_root / "schemas" / "envelope.schema.json").read_text())
    jsonschema.validate(wire, committed)
    assert wire["data"]["resolved"]["id"] == "va:fairfax-county"
    exe = wire["_execution"]
    assert exe["tool"] == "registry.resolve_jurisdiction"
    assert exe["envelope_version"] == "1"
    assert exe["request_id"]


async def test_search_sources_by_capability():
    wire = await _call("registry.search_sources",
                       {"capability": "zoning.lookup"})
    ids = [s["id"] for s in wire["data"]["sources"]]
    assert "va-fairfax-parcels-zoning" in ids
    assert wire["data"]["record_count"] == len(ids)


async def test_search_sources_unknown_capability_is_typed_error():
    server = build_server(build_ctx(), profile="all")
    async with Client(server) as client:
        res = await client.call_tool("registry.search_sources",
                                     {"capability": "unicorns.lookup"})
    assert res.is_error is True
    assert "vocabulary" in res.content[0].text


async def test_describe_source_shows_terms_and_limits():
    wire = await _call("registry.describe_source",
                       {"source_id": "va-fairfax-parcels-zoning"})
    src = wire["data"]["source"]
    assert src["terms_url"].startswith("https://www.fairfaxcounty.gov")
    assert src["known_limitations"]
    assert src["data_classification"] == "open"


async def test_describe_unknown_source_is_empty_not_error():
    wire = await _call("registry.describe_source", {"source_id": "nope"})
    assert wire["data"]["source"] is None
    assert wire["coverage"]["result"] == "empty"


async def test_source_status_defaults_to_unknown_operational():
    wire = await _call("registry.source_status", {})
    rows = {r["id"]: r for r in wire["data"]["sources"]}
    assert rows["va-fairfax-parcels-zoning"]["operational_state"] == "unknown"
