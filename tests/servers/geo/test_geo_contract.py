"""Geo contract tier: envelope validity, coverage honesty, budgets, ordering —
through the in-memory MCP client, so the whole wire path is what's tested."""
import json

import jsonschema
import pytest
from mcp.client import Client

from commonwealth.servers.build import build_server
from tests.conftest import build_ctx


@pytest.fixture()
def server():
    return build_server(build_ctx(), profile="all")


async def test_every_tool_has_output_schema_and_stable_order(server):
    async with Client(server) as client:
        first = [t.name for t in (await client.list_tools()).tools]
        second = [t.name for t in (await client.list_tools()).tools]
    assert first == second, "tools/list must be deterministic"
    assert first == ["registry.resolve_jurisdiction", "registry.search_sources",
                     "registry.describe_source", "registry.source_status",
                     "geo.find_parcel", "geo.find_zoning",
                     "geo.find_boundaries", "geo.find_address",
                     "geo.resolve_location", "geo.find_buildings",
                     "geo.find_landmarks", "geo.find_roads",
                     "geo.find_environmental_sites",
                     "civic.get_code_section"], (
        "registration order changed — that is a contract change, make it "
        "deliberately")
    async with Client(server) as client:
        missing = [t.name for t in (await client.list_tools()).tools
                   if t.output_schema is None]
    assert missing == [], f"tools without output schema: {missing}"


async def test_find_zoning_by_pin_full_envelope(server, sample_pin,
                                                project_root):
    async with Client(server) as client:
        res = await client.call_tool(
            "geo.find_zoning",
            {"jurisdiction": "Fairfax County", "pin": sample_pin})
    assert res.is_error is False
    wire = res.structured_content
    committed = json.loads(
        (project_root / "schemas" / "envelope.schema.json").read_text())
    jsonschema.validate(wire, committed)

    cov = wire["coverage"]
    assert cov["registry"] == "covered"
    assert cov["execution"] == "complete"
    assert cov["result"] == "hit"
    assert "va:fairfax-county" in cov["jurisdictions_searched"]

    codes = {w["code"] for w in wire["warnings"]}
    assert "screening_only" in codes
    assert "freshness_unavailable" in codes, (
        "this layer publishes no lastEditDate; the honest-null warning "
        "must fire")

    districts = {r["district"]
                 for blk in wire["data"]["results"] for r in blk["records"]}
    assert districts == {"R-3"}, "recorded parcel's district"


async def test_every_material_record_resolves_evidence(server, sample_pin):
    async with Client(server) as client:
        res = await client.call_tool(
            "geo.find_parcel",
            {"jurisdiction": "Fairfax County", "pin": sample_pin})
    wire = res.structured_content
    evidence_ids = {e["id"] for e in wire["evidence"]}
    source_ids = {s["id"] for s in wire["provenance"]}
    records = [r for blk in wire["data"]["results"] for r in blk["records"]]
    assert records, "the recorded PIN must return its parcel"
    for r in records:
        assert r["evidence_ref"] in evidence_ids, r
    for e in wire["evidence"]:
        assert e["source_ref"] in source_ids, e


async def test_ambiguous_jurisdiction_requires_user_choice(server):
    async with Client(server) as client:
        res = await client.call_tool(
            "geo.find_zoning", {"jurisdiction": "fairfax", "pin": "whatever"})
    wire = res.structured_content
    assert wire["requires_user_choice"] is True
    ids = [c["id"] for c in wire["data"]["candidates"]]
    assert ids == ["va:fairfax-city", "va:fairfax-county"]


async def test_registry_gap_trap_craig_county(server):
    """design/provenance-envelope.md § 8.3: a registry gap must never read
    as an empty search of covered systems. VGIN's statewide layer now
    covers parcel.lookup everywhere in Virginia, so the real remaining gap
    is zoning.lookup — no statewide zoning source exists, and Craig County
    has no local one."""
    async with Client(server) as client:
        res = await client.call_tool(
            "geo.find_zoning",
            {"jurisdiction": "Craig County", "pin": "123"})
    cov = res.structured_content["coverage"]
    assert cov["registry"] == "none"
    assert cov["result"] == "empty"
    gaps = {g["jurisdiction"]: g["reason"]
            for g in cov["jurisdictions_unavailable"]}
    assert gaps["va:craig-county"] == "no_registered_source"


async def test_data_token_budget(server, sample_pin):
    from commonwealth.core.envelope import DATA_TOKEN_BUDGET
    async with Client(server) as client:
        for tool, args in [
            ("geo.find_zoning", {"jurisdiction": "Fairfax County",
                                 "pin": sample_pin}),
            ("geo.find_parcel", {"jurisdiction": "Fairfax County",
                                 "pin": sample_pin}),
        ]:
            res = await client.call_tool(tool, args)
            data = res.structured_content["data"]
            estimate = len(json.dumps(data, separators=(",", ":"))) // 4
            print(f"{tool}: ~{estimate} data tokens "
                  f"(budget {DATA_TOKEN_BUDGET})")
            assert estimate <= DATA_TOKEN_BUDGET


async def test_invalid_args_surface_as_tool_error(server):
    async with Client(server) as client:
        res = await client.call_tool(
            "geo.find_parcel", {"jurisdiction": "Fairfax County"})
    assert res.is_error is True
    text = res.content[0].text
    assert "pin" in text and "point" in text.lower() or "lon" in text
