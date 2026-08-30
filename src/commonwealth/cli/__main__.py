"""The `commonwealth` CLI (design/cli.md; debug/contributor surface).

Every command prints the count of things it actually examined and exits
nonzero on failure — an empty examination is an error, not a pass.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from .. import __version__
from ..adapters import arcgis as arcgis_mod
from ..adapters.base import HttpFetcher, egress_policy_for
from ..core import toolreg
from ..core.envelope import utc_now_iso
from ..core.errors import CommonwealthError
from ..core.registry import (INVENTORY_ADAPTER, SourceManifest,
                             validate_manifest)
from ..runtime import PROJECT_ROOT, SOURCES_DIR, RuntimeContext, load_context

FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "sources"


def _load_ctx() -> RuntimeContext:
    return load_context()


def _fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


# --- doctor ----------------------------------------------------------------

def cmd_doctor(args: argparse.Namespace) -> int:
    problems = 0
    print(f"commonwealth {__version__}")
    print(f"python {sys.version.split()[0]}")
    try:
        import mcp
        import importlib.metadata
        print(f"mcp sdk {importlib.metadata.version('mcp')}")
    except ImportError as err:
        print(f"✗ mcp sdk not importable: {err}")
        problems += 1

    try:
        ctx = _load_ctx()
    except Exception as err:  # noqa: BLE001 — doctor reports, then exits nonzero
        print(f"✗ context failed to load: {err.__class__.__name__}: {err}")
        return 1
    print(f"jurisdiction table: {len(ctx.jurisdictions)} rows")
    print(f"source manifests: {len(ctx.sources.manifests)} "
          f"(registry revision {ctx.sources.revision})")

    rc = _validate_all(ctx, quiet=True)
    if rc != 0:
        print("✗ manifest validation failed (run `commonwealth sources "
              "validate` for detail)")
        problems += 1
    else:
        print(f"manifests valid: {len(ctx.sources.manifests)}/"
              f"{len(ctx.sources.manifests)}")

    from ..servers.build import build_server
    server = build_server(ctx, profile="default")
    tools = asyncio.run(_tool_names(server))
    print(f"default profile: {len(tools)} tools: {', '.join(tools)}")

    if args.live:
        inventory = 0
        for m in ctx.sources.manifests.values():
            if m.adapter.type == "arcgis":
                layers = m.adapter.model_dump().get("layers", {})
                for layer in layers:
                    try:
                        h = asyncio.run(ctx.arcgis.health(m, layer))
                        mark = "✓" if h["healthy"] else "✗"
                        print(f"{mark} live {m.id}/{layer}: "
                              f"{h['feature_count']} features "
                              f"(min {h['min_expected']})")
                        if not h["healthy"]:
                            problems += 1
                    except CommonwealthError as err:
                        print(f"✗ live {m.id}/{layer}: {err.code}: {err}")
                        problems += 1
            elif m.adapter.type == "virginia_law":
                known = m.health.expect.get("known_section")
                try:
                    section = asyncio.run(
                        ctx.virginia_law.get_section(m, known))
                    healthy = section is not None
                    mark = "✓" if healthy else "✗"
                    print(f"{mark} live {m.id}: known section {known!r} "
                          f"{'found' if healthy else 'NOT FOUND'}")
                    if not healthy:
                        problems += 1
                except CommonwealthError as err:
                    print(f"✗ live {m.id}: {err.code}: {err}")
                    problems += 1
            elif m.adapter.type == "arcgis_geocode":
                # A locator that answers HTTP 200 with zero candidates for
                # everything is broken in a way a reachability check
                # cannot see, so the probe geocodes a known address.
                try:
                    h = asyncio.run(ctx.geocoder.health(m))
                    mark = "✓" if h["healthy"] else "✗"
                    print(f"{mark} live {m.id}: {h['address']!r} -> "
                          f"{h['candidates']} candidate(s), best score "
                          f"{h['best_score']} (min {h['min_score']})")
                    if not h["healthy"]:
                        problems += 1
                except CommonwealthError as err:
                    print(f"✗ live {m.id}: {err.code}: {err}")
                    problems += 1
            elif m.adapter.type == INVENTORY_ADAPTER:
                # Not a gap: an inventory row names a publisher with no
                # endpoint behind it, so there is nothing to probe and
                # counting it as a problem would make `doctor` red for
                # doing exactly what design/source-registry.md § 6.3 asks.
                inventory += 1
            else:
                print(f"? live {m.id}: no live probe wired for adapter "
                      f"type {m.adapter.type!r}")
                problems += 1
        if inventory:
            print(f"- {inventory} inventory source(s) not probed: "
                  "declared_state=proposed, no endpoint to reach")
    else:
        print("(live source probes skipped; pass --live)")

    print(f"{'✗' if problems else '✓'} doctor: {problems} problem(s)")
    if not problems:
        # design/cli.md § 2: doctor is the front door and ends with a
        # copy-pasteable next step. Until `configure` existed there was
        # nothing to point at.
        print("\nnext: point a client at it")
        print("  commonwealth configure claude-code")
        print("  commonwealth configure --help    # claude, codex, cursor, "
              "vscode")
    return 1 if problems else 0


async def _tool_names(server) -> list[str]:
    return [t.name for t in await server.list_tools()]


# --- tools -----------------------------------------------------------------

def cmd_tools_list(args: argparse.Namespace) -> int:
    from ..servers.build import registries
    specs = toolreg.expand_profile(args.profile, registries())
    for s in specs:
        print(f"{s.name:32} [{s.toolset}] v{s.contract_version}")
    print(f"{len(specs)} tools in profile {args.profile!r}")
    return 0


def cmd_tools_call(args: argparse.Namespace) -> int:
    from ..servers.build import registries
    ctx = _load_ctx()
    name = toolreg.resolve_alias(args.tool)
    spec = next((s for reg in registries().values()
                 for s in reg.tools() if s.name == name), None)
    if spec is None:
        return _fail(f"unknown tool {args.tool!r}; `commonwealth tools list "
                     "--profile all` shows what exists")
    try:
        tool_args: dict[str, Any] = json.loads(args.args)
    except json.JSONDecodeError as err:
        return _fail(f"--args is not valid JSON: {err}")
    try:
        envelope = asyncio.run(spec.fn(ctx, **tool_args))
    except CommonwealthError as err:
        print(json.dumps({"error": err.code, "message": str(err)}, indent=2))
        return 1
    print(json.dumps(envelope.model_dump(mode="json", by_alias=True),
                     indent=2))
    return 0


# --- sources ---------------------------------------------------------------

def _validate_all(ctx: RuntimeContext, quiet: bool = False) -> int:
    known_j = ctx.jurisdictions.ids()
    total_problems = 0
    checked = 0
    for path in sorted(SOURCES_DIR.rglob("*.yaml")):
        if path.name == "capabilities.yaml" or "jurisdictions" in path.parts:
            continue
        checked += 1
        rel = str(path.relative_to(PROJECT_ROOT))
        try:
            manifest = SourceManifest.model_validate(
                yaml.safe_load(path.read_text()))
        except Exception as err:  # noqa: BLE001
            if not quiet:
                print(f"✗ {rel}: schema: {err}")
            total_problems += 1
            continue
        problems = validate_manifest(manifest, rel,
                                     ctx.sources.capability_vocab, known_j)
        for p in problems:
            if not quiet:
                print(f"✗ {p.path}: {p.problem}")
        total_problems += len(problems)
        if not problems and not quiet:
            print(f"✓ {rel}")
    if checked == 0:
        if not quiet:
            print("✗ zero manifests found — that is a failure, not a pass")
        return 1
    if not quiet:
        print(f"checked {checked} manifest(s), {total_problems} problem(s)")
    return 1 if total_problems else 0


def cmd_sources_validate(args: argparse.Namespace) -> int:
    return _validate_all(_load_ctx())


def registry_stats(ctx: RuntimeContext) -> dict[str, Any]:
    """Coverage debt, counted rather than remembered.

    design/source-registry.md § 6.3: every "we should cover X someday" idea
    becomes a `proposed` manifest, so the proposed/active split is the
    measurement. Derived from the loaded registry — a hand-maintained
    mirror of these numbers anywhere is a test failure by design (§ 7)."""
    from ..core.registry import DeclaredState

    manifests = list(ctx.sources.manifests.values())
    by_state = {s.value: 0 for s in DeclaredState}
    for m in manifests:
        by_state[m.lifecycle.declared_state.value] += 1
    active = [m for m in manifests
              if m.lifecycle.declared_state == DeclaredState.active]
    answered = {cap for m in active for cap in m.capability_ids()}
    unanswered = sorted(ctx.sources.capability_vocab - answered)
    by_adapter: dict[str, int] = {}
    for m in manifests:
        by_adapter[m.adapter.type] = by_adapter.get(m.adapter.type, 0) + 1
    return {
        "total": len(manifests),
        "by_declared_state": by_state,
        "by_adapter_type": dict(sorted(by_adapter.items())),
        "capabilities_in_vocabulary": len(ctx.sources.capability_vocab),
        "capabilities_with_an_active_source": len(answered),
        "capabilities_with_no_active_source": unanswered,
        "jurisdictions_in_table": len(ctx.jurisdictions),
        "jurisdictions_with_a_local_source": len(
            {m.jurisdiction for m in active if m.jurisdiction != "va"}),
    }


def cmd_sources_stats(args: argparse.Namespace) -> int:
    ctx = _load_ctx()
    stats = registry_stats(ctx)
    if args.json:
        print(json.dumps(stats, indent=2))
        return 0
    states = stats["by_declared_state"]
    print(f"source manifests: {stats['total']}")
    for state in ("active", "proposed", "retired"):
        print(f"  {state:9} {states[state]}")
    print("adapter types: " + ", ".join(
        f"{k}={v}" for k, v in stats["by_adapter_type"].items()))
    print(f"capabilities: {stats['capabilities_with_an_active_source']}"
          f"/{stats['capabilities_in_vocabulary']} have an active source")
    for cap in stats["capabilities_with_no_active_source"]:
        print(f"  no active source: {cap}")
    print(f"jurisdictions: {stats['jurisdictions_with_a_local_source']}"
          f"/{stats['jurisdictions_in_table']} have a source of their own "
          "(statewide sources cover the rest)")
    return 0


def cmd_sources_probe(args: argparse.Namespace) -> int:
    ctx = _load_ctx()
    ids = [args.source_id] if args.source_id else sorted(ctx.sources.manifests)
    problems = 0
    checked = 0
    for sid in ids:
        m = ctx.sources.get(sid)
        if m is None:
            return _fail(f"unknown source {sid!r}")
        if m.adapter.type != "arcgis":
            print(f"- {sid}: no probe for adapter {m.adapter.type!r}")
            continue
        params = arcgis_mod.ArcGISParams.model_validate(
            m.adapter.model_dump(exclude={"type"}))
        for layer in sorted(params.layers):
            checked += 1
            try:
                h = asyncio.run(ctx.arcgis.health(m, layer))
            except CommonwealthError as err:
                print(f"✗ {sid}/{layer}: {err.code}: {err}")
                problems += 1
                continue
            mark = "✓" if h["healthy"] else "✗"
            print(f"{mark} {sid}/{layer}: {h['feature_count']} features "
                  f"(min {h['min_expected']})")
            if not h["healthy"]:
                problems += 1
    print(f"probed {checked} layer(s), {problems} problem(s)")
    return 1 if problems or checked == 0 else 0


class _RecordingFetcher:
    """Wraps the real fetcher and records every exchange for replay."""

    def __init__(self, inner: HttpFetcher) -> None:
        self.inner = inner
        self.exchanges: list[dict] = []

    async def fetch_json(self, url: str, params: dict) -> dict:
        payload = await self.inner.fetch_json(url, params)
        self.exchanges.append({
            "url": url,
            "params": {k: str(v) for k, v in params.items()},
            "response": payload})
        return payload


async def _sample_boundaries(adapter, m, params, ctx) -> dict:
    """Recording plan for a boundary source. Deliberately records the
    hard cases, not the easy one: the Fairfax City/County pair the whole
    jurisdiction model exists for, the one locality the publisher ships as
    two polygons, a town (a different layer with a different key), and the
    point-in-polygon lookups that back jurisdiction resolution — including
    a point in open water, because 'no jurisdiction here' has to replay
    as faithfully as a hit."""
    from ..domains.geo import BOUNDARY_SIMPLIFY_DEGREES
    out: dict[str, Any] = {}
    for layer in sorted(params.layers):
        out[f"health:{layer}"] = await adapter.health(m, layer)

    async def boundary(layer: str, where: dict[str, str], label: str) -> None:
        q = await adapter.query(m, layer, where_equals=where,
                                return_geometry=True, return_centroid=True,
                                simplify_tolerance=BOUNDARY_SIMPLIFY_DEGREES)
        out[label] = {"where": where, "record_count": len(q.records),
                      "names": [r.canonical.get("full_name")
                                for r in q.records]}

    state = ctx.jurisdictions.get("va")
    state_fips = state.fips if state else "51"
    await boundary("localities", {"fips": "51059"}, "fairfax_county")
    await boundary("localities", {"fips": "51600"}, "fairfax_city")
    # The publisher ships Prince George as two polygons under one FIPS.
    await boundary("localities", {"fips": "51149"}, "prince_george_split")
    await boundary("towns", {"place_fips": f"{state_fips}81072"}, "vienna_town")
    await boundary("localities", {"fips": "51999"}, "no_such_fips")

    from ..domains.containment import BOUNDARY_PROXIMITY_METERS

    async def at_point(lon: float, lat: float, label: str) -> None:
        hits, nearby = {}, {}
        for layer in ("localities", "towns"):
            q = await adapter.query(m, layer, geometry_point=(lon, lat))
            hits[layer] = [r.canonical.get("full_name") for r in q.records]
            # The buffered companion query backs the boundary_precision
            # straddle check, so it has to be in the recording too.
            bq = await adapter.query(
                m, layer, geometry_point=(lon, lat),
                distance_meters=BOUNDARY_PROXIMITY_METERS)
            nearby[layer] = [r.canonical.get("full_name") for r in bq.records]
        out[label] = {"point": [lon, lat], "hits": hits, "within_buffer": nearby}

    # Fairfax City centre: the canonical trap. Must return the city alone.
    await at_point(-77.3064, 38.8462, "point_fairfax_city")
    # Vienna centre: town AND its parent county, the layered-authority case.
    await at_point(-77.2653, 38.9012, "point_vienna_town")
    # Fairfax County away from any city or town.
    await at_point(-77.2500, 38.8000, "point_fairfax_county")
    # Atlantic Ocean off Virginia Beach: outside every polygon.
    await at_point(-74.5000, 36.5000, "point_open_water")
    # ~30 m inside Fairfax County but hard against the Fairfax City line:
    # the boundary-straddle case design/jurisdiction-resolution.md § 3.7
    # names. Chosen from a real vertex of the city's own polygon.
    await at_point(-77.26917, 38.85378, "point_on_city_county_line")
    # Virginia Beach: recorded when the table was a 14-row seed and this
    # was the "source knows it, we do not" path. The table now carries it,
    # so the recording backs the opposite assertion plus a reduced-table
    # test of the unmapped branch.
    await at_point(-75.9780, 36.8529, "point_untabled_locality")
    # The two coordinates geo.resolve_location lands on after geocoding
    # design/jurisdiction-resolution.md § 3's address traps. Copied from
    # the composite locator's own recorded responses (the fixture at
    # tests/fixtures/sources/va-vgin-composite-locator), because the
    # containment step replays these exact floats.
    await at_point(-77.15375027322, 38.770195471615,
                   "point_geocoded_alexandria_mailing_address")
    await at_point(-77.26436153964, 38.90067620715,
                   "point_geocoded_vienna_address")
    return out


async def _sample_addresses(adapter, m, params, ctx) -> dict:
    """Recording plan for the address-point layer. Records the postal-city
    trap (a Fairfax County address whose mailing city is an independent
    city it is not in) and the ZIP distinct queries that back
    geo.resolve_location's ZIP path — one ZIP inside a single locality,
    one spanning three, and one that matches nothing."""
    del ctx
    out: dict[str, Any] = {}
    for layer in sorted(params.layers):
        out[f"health:{layer}"] = await adapter.health(m, layer)

    # Chosen live: a Fairfax County address whose postal city is
    # Alexandria, an independent city it is not in.
    trap = await adapter.query(
        m, "addresses", where_equals={"fips": "51059"},
        where_prefix={"full_address": "4501 CARLBY LN"})
    out["postal_city_trap"] = {
        "prefix": "4501 CARLBY LN", "fips": "51059",
        "record_count": len(trap.records),
        "po_name_vs_locality": [(r.canonical.get("po_name"),
                                 r.canonical.get("locality"))
                                for r in trap.records[:3]]}

    point = await adapter.query(m, "addresses",
                                geometry_point=(-77.26436153964, 38.90067620715),
                                distance_meters=100.0)
    out["by_point"] = {"record_count": len(point.records),
                       "first": [r.canonical.get("full_address")
                                 for r in point.records[:3]]}

    for zip_code, label in ((24450, "zip_multi_locality"),
                            (22180, "zip_single_locality"),
                            (0, "zip_no_match")):
        q = await adapter.query(m, "addresses",
                                where_equals={"zip_code": zip_code},
                                distinct_fields=["fips", "locality"])
        out[label] = {"zip": zip_code,
                      "localities": [(r.canonical.get("fips"),
                                      r.canonical.get("locality"))
                                     for r in q.records]}
    return out


async def _statewide_crosschecks(adapter, m, ctx) -> dict:
    """A statewide source is queried ALONGSIDE every locality's own layer
    (../../design/architecture.md decision 0005-C), so its recording has
    to carry the queries those calls actually issue — the locality's PIN
    scoped by the locality's FIPS, and the locality's sample point.

    Derived from the other sources' committed fixtures rather than a
    hand-typed list, so registering a fourth locality and re-recording
    picks it up. Before this existed the exchanges accumulated in the
    fixture by accident and a clean re-record silently dropped them.
    """
    out: dict[str, Any] = {"localities": [], "regressions": {}}
    for other in sorted(ctx.sources.manifests.values(), key=lambda x: x.id):
        if other.id == m.id or "parcel.lookup" not in other.capability_ids():
            continue
        fixture = FIXTURES_DIR / other.id / "recorded.json"
        if not fixture.exists():
            continue
        summary = json.loads(fixture.read_text()).get("summary") or {}
        pin = summary.get("sample_pin")
        j = ctx.jurisdictions.get(other.jurisdiction)
        fips = j.fips if j else None
        if not (pin and fips):
            continue
        q = await adapter.query(m, "parcels",
                                where_equals={"pin": str(pin), "fips": fips})
        row = {"source": other.id, "pin": pin, "fips": fips,
               "record_count": len(q.records)}
        # The geometry variants too: find_zoning and find_buildings ask
        # this layer for a parcel POLYGON by PIN, and both the hit and the
        # miss have to replay.
        for target, label in ((str(pin), "with_geometry"),
                              ("NO SUCH PIN", "miss_with_geometry")):
            gq = await adapter.query(
                m, "parcels", where_equals={"pin": target, "fips": fips},
                return_geometry=True)
            row[label] = len(gq.records)
        point = summary.get("sample_point")
        if point:
            pq = await adapter.query(
                m, "parcels", geometry_point=(point[0], point[1]))
            row["point_record_count"] = len(pq.records)
        out["localities"].append(row)

    fairfax = ctx.jurisdictions.get("va:fairfax-county")
    roanoke = ctx.jurisdictions.get("va:roanoke-county")
    fairfax_fixture = FIXTURES_DIR / "va-fairfax-parcels-zoning" / "recorded.json"
    if fairfax and roanoke and fairfax_fixture.exists():
        pin = json.loads(fairfax_fixture.read_text())["summary"]["sample_pin"]
        # The PR #1 regression: a locality-scoped PIN queried against the
        # statewide layer WITHOUT a FIPS filter returned another
        # jurisdiction's parcel as a false hit. Both halves are recorded —
        # the correct scoped miss for a jurisdiction that does not have
        # that PIN, and a scoped miss for a PIN nobody has.
        wrong = await adapter.query(
            m, "parcels",
            where_equals={"pin": str(pin), "fips": roanoke.fips})
        out["regressions"]["pin_scoped_to_the_wrong_locality"] = {
            "pin": pin, "fips": roanoke.fips, "jurisdiction": roanoke.id,
            "record_count": len(wrong.records)}
        miss = await adapter.query(
            m, "parcels",
            where_equals={"pin": "NO SUCH PIN", "fips": fairfax.fips})
        out["regressions"]["scoped_no_match"] = {
            "record_count": len(miss.records)}
    return out


async def _sample_roads(adapter, m, params, ctx) -> dict:
    """Recording plan for a road source. Records the same street in the
    same town from whichever of the two publishers this is, so the
    disagreement between them replays as a comparison rather than as a
    hand-written conflict."""
    from ..domains.geo import (ROAD_RADIUS_M, _jurisdiction_filter,
                               _road_layer)
    out: dict[str, Any] = {}
    for layer in sorted(params.layers):
        out[f"health:{layer}"] = await adapter.health(m, layer)

    layer_key = _road_layer(ctx, m)
    out["query_layer"] = layer_key
    # Vienna: a town inside Fairfax County, and a street both publishers
    # carry under names that do not match.
    for label, stack in (("in_town", ["va:vienna-town", "va:fairfax-county",
                                      "va"]),
                         ("in_county", ["va:fairfax-county", "va"])):
        scope = _jurisdiction_filter(ctx, m, layer_key, stack)
        q = await adapter.query(m, layer_key,
                                where_prefix={"street_name": "Center St"},
                                where_any_of=scope)
        out[f"by_name_{label}"] = {
            "scoped": scope is not None,
            "record_count": len(q.records),
            "names": sorted({str(r.canonical.get("street_name"))
                             for r in q.records})[:6]}

    point_scope = _jurisdiction_filter(
        ctx, m, layer_key, ["va:vienna-town", "va:fairfax-county", "va"])
    pq = await adapter.query(m, layer_key,
                             geometry_point=(-77.2653, 38.9012),
                             distance_meters=ROAD_RADIUS_M,
                             where_any_of=point_scope)
    out["near_point"] = {"record_count": len(pq.records),
                         "names": sorted({str(r.canonical.get("street_name"))
                                          for r in pq.records})[:6]}
    miss = await adapter.query(
        m, layer_key,
        where_prefix={"street_name": "ZZZZ NO SUCH ROAD"},
        where_any_of=_jurisdiction_filter(ctx, m, layer_key,
                                          ["va:fairfax-county", "va"]))
    out["no_match"] = {"record_count": len(miss.records)}
    return out


async def _sample_buildings(adapter, m, params, ctx) -> dict:
    """Recording plan for building footprints. Records a residential point
    (a handful of neighbours), a dense downtown point that the service
    truncates, and a parcel-geometry intersection — the composition with
    geo.find_parcel that makes the tool worth having."""
    from ..domains.geo import BUILDING_RADIUS_M
    out: dict[str, Any] = {}
    for layer in sorted(params.layers):
        out[f"health:{layer}"] = await adapter.health(m, layer)

    quiet = await adapter.query(m, "buildings",
                                geometry_point=(-77.26436153964,
                                                38.90067620715),
                                distance_meters=BUILDING_RADIUS_M)
    out["residential_point"] = {"record_count": len(quiet.records),
                                "truncated": quiet.exceeded_transfer_limit}

    # Downtown Richmond at 800 m: 998 footprints live, which is past
    # both the 25-record inline cap and the 5-page walk budget, so the
    # truncation path is proven against real density rather than a
    # synthesized flag.
    dense = await adapter.query(m, "buildings",
                                geometry_point=(-77.4360, 37.5407),
                                distance_meters=800.0)
    out["dense_urban_point"] = {"record_count": len(dense.records),
                                "truncated": dense.exceeded_transfer_limit}

    # A Richmond parcel, then the buildings on it.
    parcel_m = ctx.sources.get("va-richmond-city-parcels-zoning")
    parcel_adapter = arcgis_mod.ArcGISAdapter(
        fetcher=_RecordingFetcher(HttpFetcher(policy=egress_policy_for(
            parcel_m, arcgis_mod.ArcGISParams.model_validate(
                parcel_m.adapter.model_dump(exclude={"type"})).service_url))),
        cache=arcgis_mod.TTLCache())
    sample = await parcel_adapter.query(parcel_m, "parcels", sample_rows=1,
                                        return_geometry=True)
    if sample.records:
        pin = sample.records[0].canonical.get("pin")
        geometry = dict(sample.records[0].geometry or {})
        geometry.setdefault("spatialReference", {"wkid": 4326})
        on_parcel = await adapter.query(m, "buildings",
                                        intersect_geometry=geometry)
        out["on_parcel"] = {"pin": pin,
                            "record_count": len(on_parcel.records)}
    return out


async def _sample_landmarks(adapter, m, params, ctx) -> dict:
    """Recording plan for landmarks. Records the three query shapes plus a
    record whose LastCheck is null, because "nobody has re-checked this"
    has to replay as faithfully as a date."""
    del ctx
    from ..domains.geo import LANDMARK_RADIUS_M
    out: dict[str, Any] = {}
    for layer in sorted(params.layers):
        out[f"health:{layer}"] = await adapter.health(m, layer)

    near = await adapter.query(m, "landmarks",
                               where_equals={"fips": "51059"},
                               geometry_point=(-77.2653, 38.9012),
                               distance_meters=LANDMARK_RADIUS_M)
    out["near_vienna"] = {
        "record_count": len(near.records),
        "names": [r.canonical.get("name") for r in near.records[:5]],
        "sources": sorted({str(r.canonical.get("source_organization"))
                           for r in near.records}),
        "null_last_checked": sum(1 for r in near.records
                                 if not r.canonical.get("last_checked"))}

    by_name = await adapter.query(m, "landmarks",
                                  where_equals={"fips": "51059"},
                                  where_prefix={"name": "Vienna"})
    out["by_name_prefix"] = {"prefix": "Vienna",
                             "record_count": len(by_name.records)}

    by_type = await adapter.query(
        m, "landmarks",
        where_equals={"fips": "51059", "place_type": "Public Library Points"})
    out["by_place_type"] = {"place_type": "Public Library Points",
                            "record_count": len(by_type.records)}
    return out


def _sample_geocoder(m, ctx) -> int:
    """A locator records differently: no layers, no field mappings, one
    operation. The recorded set is § 3's postal-city traps, plus a
    deliberate no-match, because 'the locator found nothing' has to replay
    as faithfully as a hit."""
    del ctx
    from ..adapters import arcgis_geocode as geo_mod
    p = geo_mod.ArcGISGeocodeParams.model_validate(
        m.adapter.model_dump(exclude={"type"}))
    recorder = _RecordingFetcher(
        HttpFetcher(policy=egress_policy_for(m, p.service_url)))
    adapter = geo_mod.ArcGISGeocodeAdapter(fetcher=recorder,
                                           cache=arcgis_mod.TTLCache())

    async def run() -> dict:
        out: dict[str, Any] = {"health": await adapter.health(m)}
        for label, text in (
                # § 3 case 1: a mailing address whose postal city is an
                # independent city the address is not in.
                ("postal_city_trap", "6800 Beulah St, Alexandria, VA 22310"),
                # § 3 case 4: a town address, so the town AND its county
                # both have to come back.
                ("town_address", "127 Center St S, Vienna, VA 22180"),
                # A bare ZIP, recorded to prove the locator answers it with
                # ONE centroid — which is why the ZIP path does not use it.
                ("bare_zip", "24450"),
                ("no_match", "zzzz nowhere at all qqq")):
            result = await adapter.geocode(m, text)
            out[label] = {
                "query": text,
                "candidates": [(c.address, round(c.score, 2), c.matched_by)
                               for c in result.candidates],
                "confident": len(result.confident())}
        return out

    try:
        summary = asyncio.run(run_with_crosschecks())
    except CommonwealthError as err:
        return _fail(f"{err.code}: {err}")
    return _write_fixture(m, recorder, summary)


def cmd_sources_sample(args: argparse.Namespace) -> int:
    ctx = _load_ctx()
    m = ctx.sources.get(args.source_id)
    if m is None:
        return _fail(f"unknown source {args.source_id!r}")
    if m.adapter.type == "arcgis_geocode":
        return _sample_geocoder(m, ctx)
    if m.adapter.type != "arcgis":
        return _fail(f"sample supports arcgis and arcgis_geocode for now, "
                     f"not {m.adapter.type!r}")
    params = arcgis_mod.ArcGISParams.model_validate(
        m.adapter.model_dump(exclude={"type"}))
    recorder = _RecordingFetcher(
        HttpFetcher(policy=egress_policy_for(m, params.service_url)))
    adapter = arcgis_mod.ArcGISAdapter(fetcher=recorder,
                                       cache=arcgis_mod.TTLCache())

    if "road.lookup" in m.capability_ids():
        try:
            summary = asyncio.run(_sample_roads(adapter, m, params, ctx))
        except CommonwealthError as err:
            return _fail(f"{err.code}: {err}")
        return _write_fixture(m, recorder, summary)

    if "building.lookup" in m.capability_ids():
        try:
            summary = asyncio.run(_sample_buildings(adapter, m, params, ctx))
        except CommonwealthError as err:
            return _fail(f"{err.code}: {err}")
        return _write_fixture(m, recorder, summary)

    if "landmark.lookup" in m.capability_ids():
        try:
            summary = asyncio.run(_sample_landmarks(adapter, m, params, ctx))
        except CommonwealthError as err:
            return _fail(f"{err.code}: {err}")
        return _write_fixture(m, recorder, summary)

    if "address.lookup" in m.capability_ids():
        try:
            summary = asyncio.run(_sample_addresses(adapter, m, params, ctx))
        except CommonwealthError as err:
            return _fail(f"{err.code}: {err}")
        return _write_fixture(m, recorder, summary)

    if "boundary.lookup" in m.capability_ids():
        try:
            summary = asyncio.run(_sample_boundaries(adapter, m, params, ctx))
        except CommonwealthError as err:
            return _fail(f"{err.code}: {err}")
        return _write_fixture(m, recorder, summary)

    async def run() -> dict:
        out: dict[str, Any] = {}
        for layer in sorted(params.layers):
            out[f"health:{layer}"] = await adapter.health(m, layer)
        sample = await adapter.query(m, "parcels", sample_rows=2,
                                     return_geometry=True)
        if not sample.records:
            raise CommonwealthError("sample query returned zero parcels — "
                                    "cannot record a useful fixture")
        pin = sample.records[0].canonical.get("pin")
        out["sample_pin"] = pin
        await adapter.query(m, "parcels", where_equals={"pin": str(pin)})
        # A deliberately unmatched PIN records the platform's real empty
        # response, so the empty-is-not-broken tests replay reality.
        no_match = await adapter.query(m, "parcels",
                                       where_equals={"pin": "NO SUCH PIN"})
        out["no_match_pin"] = "NO SUCH PIN"
        out["no_match_count"] = len(no_match.records)
        # The same miss with geometry requested. Every tool that needs a
        # parcel POLYGON by PIN (find_zoning, find_buildings) issues this
        # shape, and its empty response has to replay too.
        await adapter.query(m, "parcels",
                            where_equals={"pin": "NO SUCH PIN"},
                            return_geometry=True)
        pq = await adapter.query(m, "parcels", where_equals={"pin": str(pin)},
                                 return_geometry=True)
        if "zoning" not in params.layers:
            return out
        geometry = dict(pq.records[0].geometry or {})
        geometry.setdefault("spatialReference", {"wkid": 4326})
        zq = await adapter.query(m, "zoning", intersect_geometry=geometry)
        out["zoning_districts"] = sorted(
            {r.canonical.get("district") for r in zq.records})
        ring = (pq.records[0].geometry or {}).get("rings", [[[None, None]]])
        vx = ring[0][0]
        if vx[0] is not None:
            # Written into the summary so the statewide source's own
            # recording can issue the same point query a real dual-source
            # call would.
            out["sample_point"] = [float(vx[0]), float(vx[1])]
            await adapter.query(m, "zoning",
                                geometry_point=(float(vx[0]), float(vx[1])))
            await adapter.query(m, "parcels",
                                geometry_point=(float(vx[0]), float(vx[1])))
        return out

    async def run_with_crosschecks() -> dict:
        out = await run()
        if m.jurisdiction == "va":
            out["cross_source"] = await _statewide_crosschecks(adapter, m, ctx)
        return out

    try:
        summary = asyncio.run(run_with_crosschecks())
    except CommonwealthError as err:
        return _fail(f"{err.code}: {err}")
    return _write_fixture(m, recorder, summary)


def _write_fixture(m: SourceManifest, recorder: "_RecordingFetcher",
                   summary: dict) -> int:
    out_dir = FIXTURES_DIR / m.id
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture = {
        "source_id": m.id,
        "recorded_at": utc_now_iso(),
        "rights": {
            "publisher": m.publisher.agency,
            "terms_url": m.access.terms_url,
            "note": "Recorded government-published responses; third-party "
                    "content excluded from the repo's CC0 grant "
                    "(../../../design/architecture.md decision 0011).",
        },
        "summary": summary,
        "exchanges": recorder.exchanges,
    }
    path = out_dir / "recorded.json"
    path.write_text(json.dumps(fixture, indent=1))
    print(f"recorded {len(recorder.exchanges)} exchanges -> "
          f"{path.relative_to(PROJECT_ROOT)}")
    print(f"sample summary: {json.dumps(summary, default=str)}")
    return 0


# --- serve -----------------------------------------------------------------

def cmd_serve(args: argparse.Namespace) -> int:
    from ..servers.build import build_server
    ctx = _load_ctx()
    server = build_server(ctx, profile=args.profile)
    print(f"serving profile {args.profile!r} over {args.transport}",
          file=sys.stderr)
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="streamable-http")
    return 0


def cmd_configure(args: argparse.Namespace) -> int:
    from . import configure as cfg

    # An unknown profile is otherwise accepted here and only rejected
    # later by expand_profile, at which point it has already been written
    # into the user's client config and the server will not start.
    from ..core import toolreg
    if args.profile not in toolreg.PROFILES:
        print(f"unknown profile {args.profile!r}; known: "
              f"{', '.join(sorted(toolreg.PROFILES))}", file=sys.stderr)
        return 2

    client_name = args.client
    if client_name in cfg.TOML_CLIENTS:
        print(f"{client_name} keeps its MCP config in TOML, which this "
              "command does not write. Add this block to it:\n")
        print(cfg.render_toml_block(args.profile))
        return 0

    client = cfg.CLIENTS.get(client_name)
    if client is None:
        known = ", ".join(sorted(set(cfg.CLIENTS) | cfg.TOML_CLIENTS))
        print(f"unknown client {client_name!r}; known: {known}",
              file=sys.stderr)
        return 2

    path = cfg.config_path(client, args.path)
    try:
        existing, before = cfg.read_config(path)
        cfg.check_servers_block(existing, client, path)
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1

    after = cfg.render(cfg.merged(existing, client, args.profile))
    if before == after:
        print(f"{path} already points at profile {args.profile!r}; "
              "nothing to do")
        return 0

    patch = cfg.diff(path, before, after)
    if args.dry_run:
        print(patch or f"would create {path}")
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(after)
    verb = "updated" if before else "created"
    print(f"{verb} {path}")
    print(f"  server {cfg.SERVER_KEY!r}, profile {args.profile!r}")
    if client.note:
        print(f"  note: {client.note}")
    others = [k for k in (existing.get(client.key) or {})
              if k != cfg.SERVER_KEY]
    if others:
        print(f"  left alone: {', '.join(sorted(others))}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="commonwealth", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="verify install, data, and (with "
                                      "--live) source reachability")
    d.add_argument("--live", action="store_true")
    d.set_defaults(fn=cmd_doctor)

    t = sub.add_parser("tools", help="list or call tools")
    tsub = t.add_subparsers(dest="tools_command", required=True)
    tl = tsub.add_parser("list")
    tl.add_argument("--profile", default="default")
    tl.set_defaults(fn=cmd_tools_list)
    tc = tsub.add_parser("call")
    tc.add_argument("tool")
    tc.add_argument("--args", default="{}")
    tc.set_defaults(fn=cmd_tools_call)

    s = sub.add_parser("sources", help="validate, probe, or sample sources")
    ssub = s.add_subparsers(dest="sources_command", required=True)
    sv = ssub.add_parser("validate")
    sv.set_defaults(fn=cmd_sources_validate)
    sp = ssub.add_parser("probe")
    sp.add_argument("source_id", nargs="?")
    sp.set_defaults(fn=cmd_sources_probe)
    sst = ssub.add_parser("stats", help="registry coverage debt: the "
                                        "proposed/active split and what "
                                        "no active source answers")
    sst.add_argument("--json", action="store_true")
    sst.set_defaults(fn=cmd_sources_stats)
    ss = ssub.add_parser("sample")
    ss.add_argument("source_id")
    ss.set_defaults(fn=cmd_sources_sample)

    cfgp = sub.add_parser("configure",
                          help="point an MCP client at this server")
    cfgp.add_argument("client",
                      help="claude, claude-code, codex, cursor, or vscode")
    cfgp.add_argument("--profile", default="default")
    cfgp.add_argument("--path", default=None,
                      help="write this file instead of the client default")
    cfgp.add_argument("--dry-run", action="store_true",
                      help="print the diff without writing")
    cfgp.set_defaults(fn=cmd_configure)

    sv2 = sub.add_parser("serve", help="run the MCP server")
    sv2.add_argument("--profile", default="default")
    sv2.add_argument("--transport", choices=["stdio", "http"],
                     default="stdio")
    sv2.set_defaults(fn=cmd_serve)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
