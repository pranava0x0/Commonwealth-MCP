"""Regressions for the three findings in PR #38's second review round.

All three are the same failure in different clothes: an answer that is
narrower, or better attested, than the data supports.
"""
import copy

import pytest

from commonwealth.adapters.arcgis_geocode import ArcGISGeocodeAdapter
from commonwealth.adapters.base import TTLCache
from commonwealth.domains.geo import (_jurisdiction_scope, _widened_note,
                                      find_address, find_roads,
                                      resolve_location)

VIENNA_STACK = ["va:vienna-town", "va:fairfax-county", "va"]


async def test_a_town_query_says_when_it_was_widened_to_the_county(cw_ctx):
    """P1. A town has no FIPS of its own — the code is its county's — so
    a layer keyed on FIPS reaches the county and no further. The filter
    is still right to apply (it is a correct superset, and it is what
    stops a locality-scoped id matching another locality's record on a
    statewide layer), but returning a county's roads labelled "Vienna"
    is a claim the data does not support."""
    env = await find_roads(cw_ctx, jurisdiction="Vienna",
                           street_name="Center St")
    note = env.data["widened_scope"]["va-vgin-road-centerlines"]
    assert "no key for Vienna (town)" in note
    assert "narrowed to Fairfax County" in note
    assert "not just the one asked about" in note


async def test_a_source_keyed_on_names_reaches_the_town_and_says_nothing(
        cw_ctx):
    """The note has to stay quiet where the scope is exact, or it becomes
    noise. VDOT keys routes on the jurisdiction NAME, so "Town of Vienna"
    is the town — which is why it returns 2 routes where the FIPS-keyed
    source returns 39 county-wide segments."""
    env = await find_roads(cw_ctx, jurisdiction="Vienna",
                           street_name="Center St")
    assert "va-vdot-lrs-routes" not in env.data.get("widened_scope", {})
    scope = _jurisdiction_scope(cw_ctx,
                                cw_ctx.sources.get("va-vdot-lrs-routes"),
                                "routes", VIENNA_STACK)
    assert scope.narrowed_to == "va:vienna-town"
    assert scope.note(cw_ctx, "va:vienna-town") is None


async def test_a_county_query_is_exact_and_carries_no_note(cw_ctx):
    env = await find_roads(cw_ctx, jurisdiction="Fairfax County",
                           street_name="Center St")
    assert "widened_scope" not in env.data


async def test_the_widening_is_reported_by_the_address_tool_too(cw_ctx):
    """The same fallback runs through `_scoped_where`, so every tool that
    uses it inherits the same imprecision."""
    env = await find_address(cw_ctx, jurisdiction="Vienna",
                             lon=-77.26436153964, lat=38.90067620715)
    block = env.data["results"][0]
    assert "narrowed to Fairfax County" in block["widened_scope"]
    assert _widened_note(cw_ctx,
                         cw_ctx.sources.get("va-vgin-address-points"),
                         "addresses",
                         ["va:fairfax-county", "va"]) is None


async def test_every_zip_locality_names_the_evidence_it_rests_on(cw_ctx):
    """P2. Each locality is a material record resting on one distinct
    publisher tuple. The evidence entries were created and their ids
    thrown away, so nothing in the answer could be traced back."""
    env = await resolve_location(cw_ctx, zip_code="24450")
    ids = {e.id for e in env.evidence}
    assert ids, "no evidence was recorded at all"
    for row in env.data["localities_touched"]:
        assert row["evidence_refs"], row
        assert set(row["evidence_refs"]) <= ids
    for cand in env.data["candidates"]:
        assert set(cand["evidence_refs"]) <= ids, cand


async def test_a_single_locality_zip_links_its_resolution(cw_ctx):
    env = await resolve_location(cw_ctx, zip_code="22180")
    resolved = env.data["resolved"]
    assert resolved["evidence_refs"]
    assert set(resolved["evidence_refs"]) <= {e.id for e in env.evidence}


def _candidate_payload() -> dict:
    return {"address": "127 CENTER ST S, VIENNA, VA, 22180",
            "location": {"x": -77.26436, "y": 38.90068},
            "score": 100.0,
            "attributes": {"Loc_name": "AddressPoint", "City": "VIENNA",
                           "Addr_type": "PointAddress", "Postal": "22180"}}


@pytest.mark.parametrize("mutation", [
    {"location": {"x": -78.0, "y": 38.90068}},
    {"score": 62.0},
    {"address": "SOMEWHERE ELSE, VA"},
])
def test_the_payload_hash_covers_the_coordinates_it_is_evidence_for(
        mutation):
    """P2. `raw` held only the candidate's `attributes`, so the hash
    excluded `location`, `score`, and `address` — and the coordinates are
    exactly what the jurisdiction answer is computed from. A response
    whose coordinates had changed could carry an identical hash, which is
    the one thing the hash exists to make impossible."""
    import asyncio

    from commonwealth.core.registry import SourceManifest
    from commonwealth.runtime import SOURCES_DIR
    import yaml

    manifest = SourceManifest.model_validate(yaml.safe_load(
        (SOURCES_DIR / "state" / "vgin-composite-locator.yaml").read_text()))

    def hash_for(candidate: dict) -> str:
        class _One:
            async def fetch_json(self, url, params):
                return {"candidates": [candidate]}
        adapter = ArcGISGeocodeAdapter(fetcher=_One(), cache=TTLCache())
        return asyncio.run(adapter.geocode(manifest, "x")).payload_hash()

    base = _candidate_payload()
    changed = copy.deepcopy(base)
    changed.update(mutation)
    assert hash_for(base) != hash_for(changed), (
        f"the hash is blind to a change in {sorted(mutation)}")
