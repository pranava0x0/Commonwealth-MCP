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
from ..core.registry import SourceManifest, validate_manifest
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
            else:
                print(f"? live {m.id}: no live probe wired for adapter "
                      f"type {m.adapter.type!r}")
                problems += 1
    else:
        print("(live source probes skipped; pass --live)")

    print(f"{'✗' if problems else '✓'} doctor: {problems} problem(s)")
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

    from ..domains.registry import BOUNDARY_PROXIMITY_METERS

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
    # Virginia Beach is a real locality the pilot jurisdiction table does
    # not carry, so this records the 'source knows it, we do not' path.
    await at_point(-75.9780, 36.8529, "point_untabled_locality")
    return out


def cmd_sources_sample(args: argparse.Namespace) -> int:
    ctx = _load_ctx()
    m = ctx.sources.get(args.source_id)
    if m is None:
        return _fail(f"unknown source {args.source_id!r}")
    if m.adapter.type != "arcgis":
        return _fail(f"sample supports arcgis only for now, not "
                     f"{m.adapter.type!r}")
    params = arcgis_mod.ArcGISParams.model_validate(
        m.adapter.model_dump(exclude={"type"}))
    recorder = _RecordingFetcher(
        HttpFetcher(policy=egress_policy_for(m, params.service_url)))
    adapter = arcgis_mod.ArcGISAdapter(fetcher=recorder,
                                       cache=arcgis_mod.TTLCache())

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
            await adapter.query(m, "zoning",
                                geometry_point=(float(vx[0]), float(vx[1])))
            await adapter.query(m, "parcels",
                                geometry_point=(float(vx[0]), float(vx[1])))
        return out

    try:
        summary = asyncio.run(run())
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
    ss = ssub.add_parser("sample")
    ss.add_argument("source_id")
    ss.set_defaults(fn=cmd_sources_sample)

    sv2 = sub.add_parser("serve", help="run the MCP server")
    sv2.add_argument("--profile", default="default")
    sv2.add_argument("--transport", choices=["stdio", "http"],
                     default="stdio")
    sv2.set_defaults(fn=cmd_serve)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
