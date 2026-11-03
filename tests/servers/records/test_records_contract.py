"""The named records server preserves the envelope and identifies its own executions."""
import json

import jsonschema
from mcp.client import Client

from commonwealth.fixtures import replay_context
from commonwealth.servers.build import build_server


async def test_records_wire(project_root):
    async with Client(build_server(replay_context(["va-eva-order-lines"]), "records")) as client:
        tools = (await client.list_tools()).tools
        result = await client.call_tool("records.search_purchases", {"order": "A204_Z0081911"})
    assert all(t.output_schema for t in tools)
    assert sum(t.name.startswith("registry.") for t in tools) == 4
    assert {t.name for t in tools if t.name.startswith("records.")} == {
        "records.search_purchases", "records.find_flood_zones", "records.find_permit_outfalls",
        "records.get_bill", "records.get_bill_votes", "records.get_election_results"}
    assert not result.is_error
    env = result.structured_content
    jsonschema.validate(env, json.loads((project_root / "schemas/envelope.schema.json").read_text()))
    assert env["_execution"]["server"] == "commonwealth-records"
    records = env["data"]["results"][0]["records"]
    assert len(records) == 6
    from urllib.parse import parse_qs, urlparse
    for e in env["evidence"]:
        params = parse_qs(urlparse(e["locator"]).query)
        filters = json.loads(params["filters"][0])
        assert filters["Order_#"] == "A204_Z0081911" and str(filters["_id"]) == e["record_id"]
    assert {e["id"] for e in env["evidence"]} == {r["evidence_refs"][0] for r in records}
    assert {e["source_ref"] for e in env["evidence"]} == {s["id"] for s in env["provenance"]}
