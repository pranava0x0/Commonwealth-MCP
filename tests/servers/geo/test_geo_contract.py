"""Geo contract tier: envelope validity, coverage honesty, budgets, ordering —
through the in-memory MCP client, so the whole wire path is what's tested."""
import json

import jsonschema
import pytest
from mcp.client import Client

from commonwealth.domains.geo import find_zoning
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
        assert r["evidence_refs"], r
        for ref in r["evidence_refs"]:
            assert ref in evidence_ids, r
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


async def test_a_registry_gap_carries_its_escalation_hint(cw_ctx):
    """design/provenance-envelope.md § 6 and § 10, and the `registry_gap`
    trap #28's Tier-2 suite scores. `EnvelopeBuilder.next_action()` had no
    call site anywhere in src/ until 2026-09-01, so the trap would have
    passed against an envelope that could never carry the hint."""
    from commonwealth.core.assemble import REGISTRY_GAP_ACTION

    env = await find_zoning(cw_ctx, jurisdiction="Craig County", pin="x")
    assert env.coverage.registry.value == "none"
    hints = [a for a in env.next_actions if a.finding == "registry_gap"]
    assert len(hints) == 1, env.next_actions
    assert hints[0].suggested_capability == REGISTRY_GAP_ACTION
    assert "zoning.lookup" in hints[0].reason, (
        "the hint does not say which capability is missing")
    assert "va:craig-county" in hints[0].reason


async def test_a_covered_answer_carries_no_hint(cw_ctx, sample_pin):
    """The hint is for a gap. On a normal answer the field drops off the
    wire entirely (§ 4.1's absent-means-none rule)."""
    env = await find_zoning(cw_ctx, jurisdiction="Fairfax County",
                            pin=sample_pin)
    assert env.next_actions == []
    assert "next_actions" not in env.model_dump(mode="json")


async def test_the_hint_comes_from_the_shared_selection_path(cw_ctx):
    """Emitted from `selection_coverage()` rather than per tool, so it
    holds across the domain instead of wherever someone remembered. Driven
    from the function rather than by calling every tool: calling them all
    would need recorded fixtures for a locality chosen precisely because
    no source covers it."""
    from commonwealth.core.assemble import (REGISTRY_GAP_ACTION,
                                            selection_coverage)
    from commonwealth.core.envelope import RegistryCoverage
    from commonwealth.domains.geo import _builder

    for capability in ("zoning.lookup", "parcel.lookup", "building.lookup",
                       "road.lookup", "landmark.lookup"):
        b = _builder(cw_ctx, "geo.test")
        dim, gaps = selection_coverage(cw_ctx.sources, capability,
                                       ["va:craig-county"], [], builder=b)
        assert dim is RegistryCoverage.none, (capability, dim)
        env = b.build({}, await _any_coverage(cw_ctx))
        assert [a.suggested_capability for a in env.next_actions] == [
            REGISTRY_GAP_ACTION], capability


async def _any_coverage(ctx):
    """A minimal coverage block, so the builder can produce an envelope
    without a real query behind it."""
    from commonwealth.core.envelope import (Coverage, ExecutionCoverage,
                                            PaginationCoverage,
                                            RegistryCoverage, ResultCoverage,
                                            SourceClaimCoverage)
    del ctx
    return Coverage(registry=RegistryCoverage.none,
                    execution=ExecutionCoverage.complete,
                    pagination=PaginationCoverage.complete,
                    source_claim=SourceClaimCoverage.unknown,
                    result=ResultCoverage.empty)


# --- result handles over the protocol (GitHub issue #33) -------------------

async def test_a_handle_resolves_as_an_mcp_resource(cw_ctx):
    """design/provenance-envelope.md § 9: the same URI is an envelope
    `resources` entry and an MCP resource. A handle a client cannot read
    is a citation to a document nobody can open."""
    from commonwealth.domains.geo import find_boundaries

    env = await find_boundaries(cw_ctx, jurisdiction="Fairfax County",
                                detail="full")
    uri = env.resources[0].uri
    async with Client(build_server(cw_ctx, profile="all")) as client:
        templates = [t.uri_template for t in
                     (await client.list_resource_templates()).resource_templates]
        assert "commonwealth://results/{result_id}" in templates
        assert "commonwealth://evidence/{result_id}" in templates
        body = json.loads((await client.read_resource(uri)).contents[0].text)
    assert body["origin"]["tool"] == "geo.find_boundaries"
    assert body["classification"] == "open"
    assert body["expires_at"] == env.resources[0].description.split(
        "Expires ")[1].split(";")[0]
    assert body["payload"]["features"]


async def test_reading_a_handle_that_does_not_exist_says_which_kind_of_gone(
        cw_ctx):
    """The SDK wraps an unexpected exception in a generic "error creating
    resource", which would throw away the difference between an expired
    handle and one that never existed. Raising ResourceError keeps the
    message the store wrote."""
    async with Client(build_server(cw_ctx, profile="all")) as client:
        with pytest.raises(Exception) as err:
            await client.read_resource("commonwealth://results/" + "0" * 32)
    assert "ResultUnavailable" in str(err.value)
    assert "re-running the original call" in str(err.value)
