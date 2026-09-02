"""geo.find_boundaries: the boundary contract and the real source quirks
it has to survive (../../../design/source-quirks.md 1-3). Everything replays the
committed VGIN recording — no live network, no synthesized shapes."""
import json

import pytest
from mcp.client import Client

from commonwealth.core.errors import InvalidQuery
from commonwealth.domains.geo import find_boundaries
from commonwealth.servers.build import build_server
from tests.conftest import build_ctx


@pytest.fixture()
def server():
    return build_server(build_ctx(), profile="all")


def _records(env) -> list[dict]:
    return [r for blk in env.data["results"] for r in blk["records"]]


async def test_independent_city_is_its_own_territory(cw_ctx):
    """Virginia's founding trap: Fairfax City is not part of Fairfax County.
    If the boundary layer ever starts answering the county for the city,
    every downstream 'whose government' answer is wrong."""
    city = await find_boundaries(cw_ctx, "Fairfax City")
    county = await find_boundaries(cw_ctx, "Fairfax County")
    assert [r["fips"] for r in _records(city)] == ["51600"]
    assert [r["fips"] for r in _records(county)] == ["51059"]
    assert _records(city)[0]["area_sq_mi"] < _records(county)[0]["area_sq_mi"]


async def test_split_polygon_locality_returns_both(cw_ctx):
    """../../../design/source-quirks.md 1: Prince George County ships as two polygons
    under one FIPS. Both come back, each with its own evidence, and nothing
    silently picks one."""
    env = await find_boundaries(cw_ctx, "Prince George County")
    records = _records(env)
    assert len(records) == 2, "a deduping regression would drop an official record"
    assert {r["fips"] for r in records} == {"51149"}
    assert len({r["record_id"] for r in records}) == 2
    assert len({r["evidence_refs"][0] for r in records}) == 2
    assert len(env.evidence) == 2
    note = env.data["results"][0]["note"]
    assert "2 separate polygons" in note and "none is picked" in note


async def test_centroid_is_labelled_as_a_label_point(cw_ctx):
    """../../../design/source-quirks.md 2: for 4 of 134 Virginia localities the
    centroid lands in a NEIGHBOURING government, so it can never be
    presented as 'a point inside this place'."""
    env = await find_boundaries(cw_ctx, "Fairfax County")
    centroid = _records(env)[0]["centroid"]
    assert set(centroid) >= {"lon", "lat", "note"}
    assert "NOT guaranteed" in centroid["note"]
    assert "containment" in centroid["note"]


async def test_record_vintage_survives_absent_layer_vintage(cw_ctx):
    """../../../design/source-quirks.md 3: the layer publishes no editingInfo, so the
    envelope must still say the layer vintage is unknown — while the
    per-record date it DOES publish is surfaced rather than thrown away."""
    env = await find_boundaries(cw_ctx, "Fairfax County")
    assert all(s.source_updated_at is None for s in env.provenance)
    assert any(w.code.value == "freshness_unavailable" for w in env.warnings)
    assert _records(env)[0]["record_updated_at"].endswith("Z")


async def test_town_uses_the_town_layer_and_names_its_county(cw_ctx):
    env = await find_boundaries(cw_ctx, "Vienna")
    assert env.data["results"][0]["layer"] == "towns"
    assert _records(env)[0]["full_name"] == "Vienna town"
    assert {a["id"] for a in env.data["layered_authorities"]} == {
        "va:fairfax-county", "va"}


async def test_state_gap_is_explained_not_just_empty(cw_ctx):
    """The source publishes localities and towns, not a state outline. An
    empty result that didn't say why would read as 'Virginia has no
    boundary'."""
    env = await find_boundaries(cw_ctx, "Virginia")
    assert env.data["results"] == []
    assert env.coverage.result.value == "empty"
    assert env.coverage.registry.value == "covered", (
        "a source WAS selectable; this is a publisher gap, not a registry gap")
    assert "publish polygons for counties" in env.data["note"]


async def test_geometry_is_opt_in_and_declared_lossy(cw_ctx):
    concise = await find_boundaries(cw_ctx, "Fairfax County")
    full = await find_boundaries(cw_ctx, "Fairfax County", detail="full")
    assert "geometry" not in _records(concise)[0]
    assert "bbox" in _records(concise)[0]
    rings = _records(full)[0]["geometry"]["rings"]
    assert rings and rings[0]
    assert any(w.code.value == "boundary_precision" for w in concise.warnings)
    assert any("geometry_simplified" in t
               for ev in full.evidence for t in ev.transformations), (
        "a lossy generalization that isn't in transformations is a lie")


async def test_bad_detail_is_rejected(cw_ctx):
    with pytest.raises(InvalidQuery):
        await find_boundaries(cw_ctx, "Fairfax County", detail="everything")


async def test_boundaries_stay_within_the_data_budget(server):
    from commonwealth.core.envelope import DATA_TOKEN_BUDGET
    async with Client(server) as client:
        res = await client.call_tool("geo.find_boundaries",
                                     {"jurisdiction": "Fairfax County"})
    data = res.structured_content["data"]
    estimate = len(json.dumps(data, separators=(",", ":"))) // 4
    print(f"geo.find_boundaries: ~{estimate} data tokens "
          f"(budget {DATA_TOKEN_BUDGET})")
    assert estimate <= DATA_TOKEN_BUDGET


# --- the result store (GitHub issue #33) -----------------------------------

async def test_full_detail_returns_generalized_rings_and_a_real_handle(
        cw_ctx):
    """0013's first acceptance case. The inline rings are the platform's
    generalization, and the handle holds what the publisher actually
    publishes. Both numbers are asserted because the point of the handle
    is that they differ."""
    env = await find_boundaries(cw_ctx, jurisdiction="Fairfax County",
                                detail="full")
    block = env.data["results"][0]
    uri = block["full_geometry_ref"]
    assert uri.startswith("commonwealth://results/")
    assert [r.uri for r in env.resources] == [uri]

    inline_vertices = block["records"][0]["vertex_count"]
    stored = cw_ctx.results.get(uri)
    full_vertices = sum(
        len(ring)
        for feature in stored.payload["features"]
        for ring in (feature["geometry"] or {}).get("rings", []))
    assert full_vertices > inline_vertices, (
        "the handle holds no more detail than the inline rings, so it is "
        "not worth the second request")
    assert stored.payload["spatial_reference"] == {"wkid": 4326}


async def test_the_envelope_states_when_the_handle_stops_resolving(cw_ctx):
    env = await find_boundaries(cw_ctx, jurisdiction="Fairfax County",
                                detail="full")
    stored = cw_ctx.results.get(env.data["results"][0]["full_geometry_ref"])
    assert stored.expires_at in env.resources[0].description
    assert stored.expires_at, "an unexpiring handle is a retention policy"


async def test_the_generalization_warning_names_the_handle(cw_ctx):
    """The warning used to end at "do not use it to decide which side of a
    line an address falls on" and offer nothing further. It can now say
    where the real geometry is."""
    env = await find_boundaries(cw_ctx, jurisdiction="Fairfax County",
                                detail="full")
    warning = next(w for w in env.warnings
                   if w.code.value == "boundary_precision")
    assert env.data["results"][0]["full_geometry_ref"] in warning.message


async def test_concise_makes_no_second_request_and_mints_no_handle(cw_ctx):
    """The extra request is the caller's choice. A concise answer is the
    common case and must not pay for a payload nobody asked for."""
    env = await find_boundaries(cw_ctx, jurisdiction="Fairfax County")
    assert env.resources == []
    assert "full_geometry_ref" not in env.data["results"][0]
    warning = next(w for w in env.warnings
                   if w.code.value == "boundary_precision")
    assert "detail='full'" in warning.message, (
        "a concise answer should say the full geometry is obtainable")
