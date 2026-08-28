"""Registry-tool logic called directly (no MCP layer)."""
from commonwealth.domains.registry import (describe_source,
                                           resolve_jurisdiction,
                                           search_sources, source_status)


async def test_resolve_hit_carries_evidence_for_the_row(cw_ctx):
    env = await resolve_jurisdiction(cw_ctx, "Fairfax County")
    assert env.data["resolved"]["id"] == "va:fairfax-county"
    assert [e.record_id for e in env.evidence] == ["va:fairfax-county"]
    assert env.provenance[0].source_id == "commonwealth-jurisdictions"
    assert env.warnings == [], "project data must not fire the freshness "\
                               "warning meant for government layers"


async def test_resolve_empty_is_empty(cw_ctx):
    env = await resolve_jurisdiction(cw_ctx, "Narnia")
    assert env.coverage.result.value == "empty"
    assert env.requires_user_choice is False


async def test_search_with_no_hits_is_empty_not_error(cw_ctx):
    env = await search_sources(cw_ctx, text="submarines")
    assert env.data["record_count"] == 0
    assert env.coverage.result.value == "empty"


async def test_search_filters_compose(cw_ctx):
    env = await search_sources(cw_ctx, jurisdiction="va:fairfax-county",
                               capability="parcel.lookup")
    assert [s["id"] for s in env.data["sources"]] == [
        "va-fairfax-parcels-zoning"]


async def test_status_row_count_matches_registry(cw_ctx):
    env = await source_status(cw_ctx)
    assert env.data["record_count"] == len(cw_ctx.sources.manifests)


async def test_describe_reflects_manifest_fields(cw_ctx):
    env = await describe_source(cw_ctx, "va-fairfax-parcels-zoning")
    manifest = cw_ctx.sources.get("va-fairfax-parcels-zoning")
    assert env.data["source"]["authority_notes"] == manifest.authority_notes
