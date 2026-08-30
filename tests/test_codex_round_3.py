"""Regressions for the eleven findings in PR #38's later review rounds.

Nine of the eleven are three classes I fixed in one place and not the
others: jurisdiction scoping on point paths, `evidence_refs` on material
records, and provenance for a source that answered with nothing. Where a
class can be checked as a class rather than per tool, it is — that is the
only thing that stops the next instance slipping.
"""
import asyncio

import pytest
import yaml

from commonwealth.core.jurisdiction import JurisdictionTable
from commonwealth.domains.geo import (find_address, find_buildings,
                                      find_landmarks, find_parcel,
                                      find_roads, find_zoning,
                                      resolve_location)
from commonwealth.domains.registry import resolve_jurisdiction
from commonwealth.runtime import SOURCES_DIR

JURISDICTIONS = SOURCES_DIR / "jurisdictions"


# --- class: every point path is scoped to the jurisdiction ----------------

@pytest.mark.parametrize("tool,kwargs,layer", [
    (find_address, {"lon": -77.26436153964, "lat": 38.90067620715},
     "addresses"),
    (find_buildings, {"lon": -77.26436153964, "lat": 38.90067620715},
     "buildings"),
    (find_landmarks, {"lon": -77.2653, "lat": 38.9012}, "landmarks"),
])
async def test_every_buffered_point_path_carries_the_jurisdiction_filter(
        cw_ctx, monkeypatch, tool, kwargs, layer):
    """A buffered point query near a locality line returns the
    neighbour's records while the envelope reports only the jurisdiction
    that was asked for. Addresses were fixed in one round and buildings
    were still open in the next, which is why this is parametrized over
    the tools rather than written once per tool."""
    seen: list[dict] = []
    real = cw_ctx.arcgis.query

    async def spy(manifest, layer_key, **kw):
        if layer_key == layer:
            seen.append(kw)
        return await real(manifest, layer_key, **kw)

    monkeypatch.setattr(cw_ctx.arcgis, "query", spy)
    await tool(cw_ctx, jurisdiction="Vienna", **kwargs)
    assert seen, f"no {layer} query was issued"
    assert seen[0].get("where_equals") == {"fips": "51059"}, seen[0]


async def test_a_name_keyed_source_is_not_name_filtered_by_a_point_query(
        cw_ctx):
    """VDOT leaves its jurisdiction NAME blank on the ~6,500 routes that
    span localities, and its own manifest says those are meant to be
    found by proximity. ANDing the name onto a geometry filter dropped
    exactly those — a query beside an interstate would not return the
    interstate."""
    env = await find_roads(cw_ctx, jurisdiction="Vienna",
                           lon=-77.2653, lat=38.9012)
    assert env.data["geometry_scoped_sources"]["source_ids"] == [
        "va-vdot-lrs-routes"]
    counts = {b["source_id"]: b["record_count"] for b in env.data["results"]}
    assert counts["va-vdot-lrs-routes"] == 3, (
        "the name-scoped version of this query found 2")


# --- class: a material record names the evidence it rests on --------------

async def test_a_resolved_address_names_both_the_geocode_and_the_boundary(
        cw_ctx):
    env = await resolve_location(
        cw_ctx, address="6800 Beulah St, Alexandria, VA 22310")
    ids = {e.id for e in env.evidence}
    resolved = env.data["resolved"]
    assert len(resolved["evidence_refs"]) > 1, (
        "the answer rests on a geocode AND a boundary polygon")
    assert set(resolved["evidence_refs"]) <= ids
    assert "evidence_ref" not in env.data["geocode"], "singular field"
    assert set(env.data["geocode"]["evidence_refs"]) <= ids


async def test_a_resolved_point_names_the_boundary_polygons(cw_ctx):
    env = await resolve_jurisdiction(cw_ctx, lon=-77.2653, lat=38.9012)
    resolved = env.data["resolved"]
    assert resolved["evidence_refs"], "no evidence on a point resolution"
    assert set(resolved["evidence_refs"]) <= {e.id for e in env.evidence}


async def test_ambiguous_candidates_name_their_evidence_and_government(
        cw_ctx):
    """"Cntr Steet Viena VA" returns four matches at or above the
    threshold. Two place into Vienna town and two into Fairfax County, so
    taking the locator's first result picked one of two governments
    silently.

    The first candidate is addressed FALLS CHURCH and places into Fairfax
    County, which is the postal-city trap turning up inside the ambiguity
    check — one more reason the comparison is on placed governments and
    not on the strings the locator returned.

    They are also the records whose ambiguity the caller has to judge, so
    they are material and name their evidence like any other."""
    env = await resolve_location(cw_ctx, address="Cntr Steet Viena VA")
    assert env.data["resolved"] is None
    assert env.requires_user_choice is True
    assert "in different governments" in env.data["note"]
    ids = {e.id for e in env.evidence}
    governments = set()
    for cand in env.data["candidates"]:
        assert cand["evidence_refs"] and set(cand["evidence_refs"]) <= ids
        assert cand["distinguisher"]
        governments.add(cand["jurisdiction"])
    assert governments == {"va:vienna-town", "va:fairfax-county"}, governments
    falls_church = next(c for c in env.data["candidates"]
                        if "FALLS CHURCH" in c["matched_address"])
    assert falls_church["jurisdiction"] == "va:fairfax-county", (
        "a FALLS CHURCH postal address that sits in Fairfax County")


# --- class: a source that answered with nothing was still consulted -------

async def test_a_parcel_miss_still_names_the_sources_that_answered(cw_ctx):
    """An empty answer with empty provenance hides which sources were
    even asked, and their retrieval and freshness metadata with them."""
    env = await find_buildings(cw_ctx, jurisdiction="Richmond City",
                               pin="NO SUCH PIN")
    assert env.data["results"] == []
    assert env.provenance, "no source registered for a lookup that ran"
    assert "va-richmond-city-parcels-zoning" in {
        s.source_id for s in env.provenance}


# --- a plausible wrong government is worse than no answer -----------------

async def test_a_town_layer_failure_withholds_the_county(cw_ctx,
                                                         monkeypatch):
    """If the towns query fails while localities succeeds, the county is
    a plausible WRONG answer: the point may sit in a town whose polygon
    was never retrieved, and a caller would route later queries through
    the wrong government with no sign anything was missed."""
    from commonwealth.core.errors import SourceUnavailable

    real = cw_ctx.arcgis.query

    async def flaky(manifest, layer_key, **kw):
        if layer_key == "towns":
            raise SourceUnavailable("towns layer is down (test)")
        return await real(manifest, layer_key, **kw)

    monkeypatch.setattr(cw_ctx.arcgis, "query", flaky)
    env = await resolve_jurisdiction(cw_ctx, lon=-77.2653, lat=38.9012)
    assert env.data["resolved"] is None, (
        "returned a government while the narrower layer was unreachable")
    assert "may sit in an incorporated town" in env.data["note"]
    assert env.coverage.execution.value == "partial"
    assert env.coverage.source_failures


async def test_confident_geocodes_in_one_place_still_resolve(cw_ctx):
    """The ambiguity check compares GOVERNMENTS, not distance. The
    locator's address-point and road-centerline elements return the same
    Vienna address ~40 m apart at score 100, and a distance test flagged
    that as ambiguous when it is one place."""
    env = await resolve_location(
        cw_ctx, address="127 Center St S, Vienna, VA 22180")
    assert env.data["resolved"]["id"] == "va:vienna-town"
    assert env.requires_user_choice is False


# --- data: two dissolved towns were registered as live governments --------

@pytest.mark.parametrize("slug", ["columbia-town", "st-charles-town"])
def test_a_dissolved_town_has_no_row(slug):
    """Columbia and St. Charles are Census Designated Places — statistical
    areas with no government (FUNCSTAT 'S' in TIGERweb's current and 2020
    layers, checked 2026-08-30). VGIN's towns layer still carries their
    polygons, and reading that absence as a Census coverage quirk is how
    both got registered as live towns. Same trap as Bedford, two rows
    over."""
    assert not (JURISDICTIONS / f"{slug}.yaml").exists()
    table = JurisdictionTable.load(JURISDICTIONS)
    assert table.get(f"va:{slug.replace('-town', '')}-town") is None


@pytest.mark.parametrize("name,successor", [
    ("Town of Columbia", "va:fluvanna-county"),
    ("Town of St. Charles", "va:lee-county"),
])
def test_a_dissolved_towns_name_resolves_to_its_county(name, successor):
    """The territory reverted to county governance, so the county is the
    successor — the same rule Bedford uses, one level down."""
    table = JurisdictionTable.load(JURISDICTIONS)
    r = table.resolve(name)
    assert r.resolved is not None and r.resolved.id == successor, name
    assert r.basis == "former_name"


def test_the_generator_refuses_a_place_census_calls_unincorporated():
    """The towns half of the cross-check, which did not exist: VGIN's
    layer is the only source that had to agree with itself."""
    import sys
    from commonwealth.runtime import PROJECT_ROOT
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    import build_jurisdictions as gen
    import inspect

    src = inspect.getsource(gen.town_rows)
    assert "Incorporated Places" in src and "continue" in src, (
        "a town absent from Census's incorporated list must be skipped")
    assert not hasattr(gen, "intersecting_localities"), (
        "the polygon-intersection workaround existed to give those places "
        "a parent; it should be gone with them")


# --- a historical name must not answer silently ---------------------------

async def test_a_geo_tool_warns_on_a_historical_jurisdiction_name(cw_ctx):
    """Every geo tool's description tells the caller to pass the
    jurisdiction string as given, so a historical name reaches them as
    readily as it reaches registry.resolve_jurisdiction — and answering
    it silently returns current data under a dead government's name."""
    # find_zoning, because Bedford has no registered zoning source: the
    # warning has to fire on the RESOLUTION, before any source is
    # queried, which is also what keeps this test offline.
    env = await find_zoning(cw_ctx, jurisdiction="Bedford City",
                            pin="ANY-PIN")
    warning = next(w for w in env.warnings if w.code.value == "alias_match")
    assert "no longer exists" in warning.message
    assert "Bedford (town)" in warning.message


async def test_a_current_jurisdiction_name_raises_no_such_warning(cw_ctx):
    env = await find_zoning(cw_ctx, jurisdiction="Richmond City",
                            pin="C0010126019")
    assert not [w for w in env.warnings if w.code.value == "alias_match"]


# --- the geocoder's declared probe was unreachable from the CLI -----------

def test_sources_probe_dispatches_on_every_active_adapter_type():
    """`sources probe <locator>` reported "no probe", examined zero
    layers, and exited nonzero, while the manifest declared a real probe
    and the adapter implemented it. Checked by reading the dispatch, so
    the test stays offline."""
    import ast
    from commonwealth.runtime import PROJECT_ROOT

    tree = ast.parse((PROJECT_ROOT / "src" / "commonwealth" / "cli" /
                      "__main__.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "cmd_sources_probe")
    handled = {n.value for n in ast.walk(fn)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    from commonwealth.core.registry import SourceRegistry
    active = {m.adapter.type for m in
              SourceRegistry.load(SOURCES_DIR).manifests.values()
              if m.lifecycle.declared_state.value == "active"}
    missing = sorted(a for a in active if a not in handled)
    assert missing == [], (
        f"`sources probe` has no branch for active adapter type(s): "
        f"{missing}")


# --- round 6: three smaller ones -----------------------------------------

@pytest.mark.parametrize("blank", ["   ", "\t", "\n  "])
async def test_a_blank_address_is_a_caller_error_not_an_outage(cw_ctx,
                                                               blank):
    """A whitespace-only address is truthy, so it passed the
    exactly-one-input check and failed inside the adapter — where the
    broad handler turned it into an envelope saying the geocoder was
    unreachable. False outage telemetry, plus advice to retry something
    that can never work."""
    from commonwealth.core.errors import InvalidQuery

    with pytest.raises(InvalidQuery) as err:
        await resolve_location(cw_ctx, address=blank)
    assert "exactly one" in str(err.value)


async def test_a_recorded_terms_gap_is_visible_in_describe_source(cw_ctx):
    """DEQ's `terms_notes` says "see terms_gap" and this tool omitted the
    field, so the one caveat a caller most needs before using a source
    pointed at nothing."""
    from commonwealth.domains.registry import describe_source

    env = await describe_source(cw_ctx,
                                source_id="va-deq-water-quality-stations")
    src = env.data["source"]
    assert "see terms_gap" in src["terms_notes"]
    assert src["terms_gap"], "the field the notes point at"
    assert "not a licence" in src["terms_gap"]


async def test_a_source_with_no_gap_omits_the_field(cw_ctx):
    """Absent when the review came back clean, so its presence means
    something."""
    from commonwealth.domains.registry import describe_source

    env = await describe_source(cw_ctx, source_id="va-vgin-statewide-parcels")
    assert "terms_gap" not in env.data["source"]


def test_the_live_demo_build_tracks_the_geocoders_requests():
    """The page presents `http_calls` as the real outbound trail. A
    standalone adapter in live mode left the locator's request out of it
    while the page still claimed completeness."""
    import inspect
    import sys

    from commonwealth.runtime import PROJECT_ROOT
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    import build_site

    src = inspect.getsource(build_site._geocoder)
    assert "fetcher=tracker" in src
    assert src.count("ArcGISGeocodeAdapter(") == 1, (
        "an untracked branch is how the live trail lost the locator")


# --- round 7 -------------------------------------------------------------

def test_towns_that_cross_a_county_line_name_every_county():
    """Twenty of Virginia's incorporated towns straddle a line — Herndon
    is in Fairfax and Loudoun, Farmville in Prince Edward and Cumberland.
    An interior point finds one county and silently loses the rest, so
    the authority stack said one government governed ground two do."""
    table = JurisdictionTable.load(JURISDICTIONS)
    straddling = [jid for jid in table.ids()
                  if table.get(jid).also_within]
    assert len(straddling) >= 19, straddling
    herndon = table.get("va:herndon-town")
    assert herndon.parent == "va:fairfax-county"
    assert herndon.also_within == ["va:loudoun-county"]


def test_a_straddling_town_surfaces_both_counties_in_its_stack():
    table = JurisdictionTable.load(JURISDICTIONS)
    r = table.resolve("Town of Herndon")
    rels = {a["id"]: a["relationship"] for a in r.layered_authorities}
    assert rels["va:fairfax-county"] == "parent-county"
    assert rels["va:loudoun-county"] == "also-within-county"


async def test_a_bare_zip_through_the_address_parameter_is_still_a_zip(
        cw_ctx):
    """The locator answers a bare ZIP with one centroid, which is the
    one-to-many-collapsed-to-one failure the ZIP path exists to prevent.
    Reaching it through the other parameter got the wrong answer."""
    env = await resolve_location(cw_ctx, address="24450")
    assert env.data["resolved"] is None
    assert env.requires_user_choice is True
    assert len(env.data["localities_touched"]) == 3


async def test_an_unchecked_confident_candidate_forces_a_user_choice(
        cw_ctx, monkeypatch):
    """The cap checks the first four distinct coordinates. Four that
    agree and a fifth in another county read identically from there, so
    an unchecked candidate has to force the same answer disagreement
    would rather than being treated as agreement."""
    import commonwealth.domains.geo as geo

    monkeypatch.setattr(geo, "MAX_GEOCODE_CONTAINMENT_CHECKS", 1)
    env = await resolve_location(
        cw_ctx, address="127 Center St S, Vienna, VA 22180")
    assert env.data["resolved"] is None
    assert env.requires_user_choice is True
    assert "were not checked" in env.data["note"]


async def test_an_all_source_parcel_outage_is_failed_not_a_miss(
        cw_ctx, monkeypatch):
    """When every parcel source raises, nothing was searched. Reporting
    "no parcel with that PIN" turns a service being down into a fact
    about the ground."""
    from commonwealth.core.errors import SourceUnavailable

    real = cw_ctx.arcgis.query

    async def flaky(manifest, layer_key, **kw):
        if layer_key == "parcels":
            raise SourceUnavailable("parcel layer is down (test)")
        return await real(manifest, layer_key, **kw)

    monkeypatch.setattr(cw_ctx.arcgis, "query", flaky)
    env = await find_buildings(cw_ctx, jurisdiction="Richmond City",
                               pin="C0010126019")
    assert env.coverage.execution.value == "failed"
    assert env.coverage.source_failures
    assert "This is an outage" in env.data["note"]
    assert "not a statement about this PIN" in env.data["note"]
