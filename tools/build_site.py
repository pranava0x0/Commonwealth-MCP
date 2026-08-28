#!/usr/bin/env python3
"""Generate the docs site's data: catalog counts and the audit-trail demo.

Everything the page displays derives from the live registries and a real
run through the MCP layer — no hand-typed counts anywhere (the one
exception, PLANNED_SKILLS, is a declared roster with its status stated).

  .venv/bin/python tools/build_site.py --fixtures   # deterministic, offline
  .venv/bin/python tools/build_site.py --live       # against live services

Outputs docs/data/site.json and docs/data/audit-demo.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DOCS_DATA = ROOT / "docs" / "data"
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "sources"
FIXTURE = FIXTURES_DIR / "va-fairfax-parcels-zoning" / "recorded.json"


def _all_recorded_exchanges() -> list[dict]:
    """Every committed source's own fixture, merged. The demo queries the
    real (multi-source) registry, so a call can legitimately reach more
    than one source (DECISIONS.md 0005-C) — the replay pool has to cover
    whichever ones actually get queried, not just Fairfax's."""
    exchanges: list[dict] = []
    for path in sorted(FIXTURES_DIR.glob("*/recorded.json")):
        exchanges.extend(json.loads(path.read_text())["exchanges"])
    return exchanges

# The only declared (not derived) rosters on the page, each shown with its
# status or cited against the spec text it paraphrases (checked below by
# WARNING_DEFINITIONS/COVERAGE_DEFINITIONS coverage asserts).
PLANNED_SKILLS = [
    {"name": "parcel-zoning-screen", "status": "planned (developer-product phase)",
     "capabilities": ["parcel.lookup", "zoning.lookup"]},
    {"name": "legislative-impact-analysis", "status": "milestone 1b (civic)",
     "capabilities": []},
    {"name": "development-site-due-diligence",
     "status": "deferred until coverage earns the name", "capabilities": []},
]

# design/provenance-envelope.md § 3 table, transcribed with the spec's own
# wording; a test asserts this covers every dimension value the models emit.
COVERAGE_DEFINITIONS = {
    "registry": {
        "question": "Does the Source Registry cover the requested "
                     "place/capability/time at all?",
        "values": {
            "covered": "A registered source should answer this.",
            "partial": "Some but not all of what was asked is covered.",
            "none": "Commonwealth has no source for this — the gap is "
                    "named, never reported as “no results.”",
            "unknown": "Coverage could not be determined.",
        },
    },
    "execution": {
        "question": "Did the queries that should have run actually finish?",
        "values": {
            "complete": "Every source that should have been queried was.",
            "partial": "Named sources could not be checked; the answer "
                        "says which.",
            "failed": "The call failed outright; the typed error rides "
                       "alongside this envelope.",
        },
    },
    "pagination": {
        "question": "Was the record set fully paged?",
        "values": {
            "complete": "Every page was retrieved.",
            "truncated": "The source's own transfer limit cut the result "
                          "short (ArcGIS exceededTransferLimit); honestly "
                          "labeled, not silently dropped.",
            "unknown": "Paging completeness could not be determined.",
        },
    },
    "result": {
        "question": "Did anything match?",
        "values": {
            "hit": "At least one record matched.",
            "empty": "Nothing matched — a successful state, not an "
                      "error.",
        },
    },
}

# Every WarningCode member (src/commonwealth/core/envelope.py), defined from
# the spec text or the raising call site; a test asserts this dict's keys
# equal the enum exactly, so a new code fails the build until defined here.
WARNING_DEFINITIONS = {
    "screening_only": "GIS zoning is a screening layer. The adopted zoning "
        "ordinance and official zoning map govern; confirm before any "
        "legal reliance.",
    "stale_source": "The source's own update cadence was missed.",
    "freshness_unavailable": "The publisher exposes no machine-readable "
        "update date for this layer; retrieval time is known, data "
        "vintage isn't.",
    "boundary_precision": "Parcel or boundary geometry is generalized, "
        "not surveyed.",
    "alias_match": "The entity matched via a registered alias, not its "
        "exact id.",
    "mixed_vintages": "Results combine records with different as-of dates.",
    "terms_note": "The source's terms constrain reuse of this data.",
    "sensitive_public_data": "The source is classified sensitive_public: "
        "technically public, but redistribution is field-allowlisted and "
        "reviewed before the source may go active.",
    "insecure_transport": "This source is reached over plain HTTP, per a "
        "reviewed manifest exception, not HTTPS.",
    "truncated_inline": "More records were retrieved than are shown "
        "inline; narrow the query for the rest.",
}

# The demo walk: cross-tool calls that exercise resolution, ambiguity, data,
# emptiness, a registry gap, discovery, and one typed error.
DEMO_CALLS = [
    ("registry.resolve_jurisdiction", {"query": "fairfax"},
     "Ambiguous on purpose: Fairfax City vs Fairfax County"),
    ("registry.resolve_jurisdiction", {"query": "Fairfax County"},
     "Exact resolution with the authority stack"),
    ("geo.find_parcel", {"jurisdiction": "Fairfax County",
                         "pin": "__SAMPLE_PIN__"},
     "Parcel record with evidence and provenance"),
    ("geo.find_zoning", {"jurisdiction": "Fairfax County",
                         "pin": "__SAMPLE_PIN__"},
     "Zoning via parcel-geometry intersection; screening warnings"),
    ("geo.find_parcel", {"jurisdiction": "Fairfax County",
                         "pin": "__NO_MATCH_PIN__"},
     "A clean empty: covered registry, no record"),
    # VGIN's statewide layer (added 2026-08-28) covers parcel.lookup
    # everywhere in Virginia, so the remaining real gap for a
    # no-local-source county is zoning.lookup, not parcel.lookup.
    ("geo.find_zoning", {"jurisdiction": "Craig County", "pin": "123"},
     "A registry gap: coverage says none, not 'no results'"),
    ("registry.search_sources", {"capability": "zoning.lookup"},
     "What covers zoning.lookup, with authority levels"),
    ("registry.describe_source", {"source_id": "va-fairfax-parcels-zoning"},
     "Terms, limitations, and authority notes for the source"),
    ("registry.source_status", {},
     "Declared vs operational state for every registered source"),
    ("registry.search_sources", {"capability": "unicorns.lookup"},
     "A typed error: unknown capability, said plainly"),
]

# Added 2026-08-28 with the boundary source. The walk above predates
# point-in-polygon, boundaries, and the civic tool, so it showed five of
# eight tools — a demo that quietly omits a third of the surface.
DEMO_CALLS[5:5] = [
    ("registry.resolve_jurisdiction", {"lon": -77.3064, "lat": 38.8462},
     "A coordinate inside Fairfax City resolves to the CITY, never the "
     "county that surrounds it"),
    ("registry.resolve_jurisdiction", {"lon": -77.2653, "lat": 38.9012},
     "A coordinate in Vienna returns the town AND its county: both "
     "govern that ground"),
    ("geo.find_boundaries", {"jurisdiction": "Prince George County"},
     "One jurisdiction, two official polygons under one FIPS — both "
     "returned, neither picked"),
    ("civic.get_code_section", {"citation": "1-500"},
     "Code of Virginia section text with its own citation history"),
]


def build_catalog() -> dict:
    import yaml
    from commonwealth import __version__
    from commonwealth.core import toolreg
    from commonwealth.core.envelope import (
        ExecutionCoverage, PaginationCoverage, RegistryCoverage,
        ResultCoverage, WarningCode,
    )
    from commonwealth.runtime import SOURCES_DIR, load_context
    from commonwealth.servers.build import registries

    defined = set(WARNING_DEFINITIONS)
    declared = {c.value for c in WarningCode}
    if defined != declared:
        raise AssertionError(
            "WARNING_DEFINITIONS drifted from WarningCode: "
            f"missing={declared - defined} extra={defined - declared}")

    dim_enums = {"registry": RegistryCoverage, "execution": ExecutionCoverage,
                 "pagination": PaginationCoverage, "result": ResultCoverage}
    for dim, enum_cls in dim_enums.items():
        defined_vals = set(COVERAGE_DEFINITIONS[dim]["values"])
        declared_vals = {c.value for c in enum_cls}
        if defined_vals != declared_vals:
            raise AssertionError(
                f"COVERAGE_DEFINITIONS[{dim!r}] drifted from {enum_cls.__name__}: "
                f"missing={declared_vals - defined_vals} "
                f"extra={defined_vals - declared_vals}")

    ctx = load_context()
    regs = registries()

    tools = []
    for package, reg in sorted(regs.items()):
        for spec in reg.tools():
            tools.append({"name": spec.name, "package": package,
                          "toolset": spec.toolset,
                          "contract_version": spec.contract_version,
                          "description": spec.description})

    sources = []
    for m in sorted(ctx.sources.manifests.values(), key=lambda m: m.id):
        sources.append({
            "id": m.id, "name": m.name, "jurisdiction": m.jurisdiction,
            "publisher": m.publisher.agency,
            "authority_level": m.publisher.authority_level.value,
            "capabilities": sorted(m.capability_ids()),
            "data_classification": m.access.data_classification.value,
            "declared_state": m.lifecycle.declared_state.value,
            "terms_url": m.access.terms_url,
            "known_limitations": m.coverage.known_limitations,
        })

    kinds = Counter()
    trap_pairs = []
    for f in sorted((SOURCES_DIR / "jurisdictions").glob("*.yaml")):
        j = yaml.safe_load(f.read_text())
        kinds[j["kind"]] += 1
        for other in j.get("not_to_be_confused_with", []):
            pair = tuple(sorted([j["id"], other]))
            if pair not in trap_pairs:
                trap_pairs.append(pair)

    profiles = {name: len(toolreg.expand_profile(name, regs))
                for name in toolreg.PROFILES}

    jurisdictions = []
    for jid in sorted(ctx.jurisdictions.ids()):
        j = ctx.jurisdictions.get(jid)
        jurisdictions.append({
            "id": j.id, "name": j.name, "kind": j.kind.value,
            "fips": j.fips, "place_fips": j.place_fips, "parent": j.parent,
            "aliases": j.aliases,
            "not_to_be_confused_with": j.not_to_be_confused_with,
        })

    # Real coverage per capability, computed the same way a tool call
    # resolves it (registry.select over the resolved jurisdiction stack) —
    # never a client-side guess at which jurisdictions a source's
    # `jurisdiction: va` fans out to. A jurisdiction may show as covered by
    # a statewide source while still having no LOCAL one; `sources` on
    # each row says which.
    capability_coverage = {}
    for cap in sorted(ctx.sources.capability_vocab):
        covered, gaps = [], []
        for jid in sorted(ctx.jurisdictions.ids()):
            j = ctx.jurisdictions.get(jid)
            stack = [j.id] + [p.id for p in ctx.jurisdictions.parents_of(j)]
            selected = ctx.sources.select(cap, stack)
            if selected:
                covered.append({"jurisdiction": jid,
                                "sources": [m.id for m in selected]})
            else:
                gaps.append(jid)
        capability_coverage[cap] = {"covered": covered, "gaps": gaps}

    return {
        "version": __version__,
        "registry_revision": ctx.sources.revision,
        "counts": {
            # Declared, not derived from a collection: build_server() always
            # returns exactly one MCPServer (DECISIONS.md 0001, "one process").
            "servers": 1,
            "tools": len(tools),
            "packages": len(regs),
            "sources": len(sources),
            "capabilities": len(ctx.sources.capability_vocab),
            "jurisdictions": len(ctx.jurisdictions),
            "trap_pairs": len(trap_pairs),
        },
        "tools": tools,
        "sources": sources,
        "capabilities": sorted(ctx.sources.capability_vocab),
        "jurisdiction_kinds": dict(sorted(kinds.items())),
        "trap_pairs": [list(p) for p in trap_pairs],
        "profiles": profiles,
        "skills": PLANNED_SKILLS,
        "jurisdictions": jurisdictions,
        "capability_coverage": capability_coverage,
        "coverage_definitions": COVERAGE_DEFINITIONS,
        "warning_definitions": WARNING_DEFINITIONS,
    }


def build_resolver_demo(ctx) -> dict:
    """Every query the resolver playground can show, computed by calling
    the real `JurisdictionTable.resolve()` — the playground is a client-side
    lookup over this table, never a reimplementation of the algorithm, so it
    cannot drift from what the MCP tool actually returns."""
    table = ctx.jurisdictions
    queries: dict[str, dict] = {}

    def record(q: str) -> None:
        q = q.strip()
        if not q:
            return
        key = q.lower()
        if key in queries:
            return
        res = table.resolve(q)
        queries[key] = {
            "resolved": ({"id": res.resolved.id, "name": res.resolved.name,
                          "kind": res.resolved.kind.value}
                         if res.resolved else None),
            "basis": res.basis,
            "candidates": [{"id": c.id, "name": c.name, "kind": c.kind.value,
                            "distinguisher": c.distinguisher}
                           for c in res.candidates],
        }

    stems: set[str] = set()
    for jid in sorted(table.ids()):
        j = table.get(jid)
        record(j.id)
        record(j.name)
        if j.fips:
            record(j.fips)
            record(j.fips[-3:])
        for a in j.aliases:
            record(a)
        low = j.name.lower()
        for suffix in (" county", " city", " (town)"):
            if low.endswith(suffix):
                stems.add(low.removesuffix(suffix))
    for stem in sorted(stems):
        record(stem)

    return {"queries": queries, "query_list": sorted(queries)}


def _summarize_params(params: dict) -> dict:
    """Keep every param but collapse a geometry blob to its shape — the
    point is showing what was asked, not re-embedding a polygon."""
    out = {}
    for k, v in params.items():
        if k == "geometry" and isinstance(v, str) and len(v) > 120:
            rings = v.count('"rings"')
            out[k] = f"<polygon geometry, {v.count('], [') + 1} vertices>" \
                if rings else f"<geometry, {len(v)} chars>"
        else:
            out[k] = v
    return out


def _summarize_response(resp: dict) -> dict:
    if "features" in resp and isinstance(resp["features"], list):
        return {"features": len(resp["features"])}
    if "count" in resp:
        return {"count": resp["count"]}
    return {"keys": sorted(resp)[:8]}


class TrackingFetcher:
    """Wraps a fetcher to log the real (url, params, response) triples the
    adapter sends, so the site can show the actual outbound HTTP calls a
    tool call made — not just the tool's own envelope.

    With `inner=None` (live mode), there is no single fixed fetcher to wrap:
    different manifests hit different hosts, each needing its own egress
    policy. A fresh single-host HttpFetcher is built and cached per host
    seen — as safe as production's per-manifest policy (both are a
    single-host allowlist), just derived from the request URL instead of
    the manifest object, since the Fetcher protocol never sees the latter.
    """

    def __init__(self, inner=None) -> None:
        self._inner = inner
        self._live_fetchers: dict[str, Any] = {}
        self.calls: list[dict] = []

    def _fetcher_for_live(self, url: str):
        from urllib.parse import urlparse

        from commonwealth.adapters.base import HttpFetcher
        from commonwealth.core.egress import EgressPolicy
        host = (urlparse(url).hostname or "").lower()
        if host not in self._live_fetchers:
            self._live_fetchers[host] = HttpFetcher(
                policy=EgressPolicy(allowed_hosts=frozenset({host})))
        return self._live_fetchers[host]

    async def fetch_json(self, url: str, params: dict) -> dict:
        inner = self._inner or self._fetcher_for_live(url)
        response = await inner.fetch_json(url, params)
        self.calls.append({
            "url": url,
            "params": _summarize_params(params),
            "response": _summarize_response(response),
        })
        return response


async def run_demo(mode: str) -> dict:
    from mcp.client import Client
    from commonwealth.adapters.arcgis import ArcGISAdapter
    from commonwealth.adapters.base import TTLCache
    from commonwealth.adapters.replay import ReplayFetcher
    from commonwealth.core.envelope import utc_now_iso
    from commonwealth.runtime import load_context
    from commonwealth.servers.build import build_server

    recording = json.loads(FIXTURE.read_text())
    sample_pin = recording["summary"]["sample_pin"]
    no_match_pin = recording["summary"]["no_match_pin"]

    if mode == "fixtures":
        tracker = TrackingFetcher(ReplayFetcher(_all_recorded_exchanges()))
    else:
        tracker = TrackingFetcher()  # live mode: per-host HttpFetchers
    adapter = ArcGISAdapter(fetcher=tracker, cache=TTLCache())
    ctx = load_context(arcgis=adapter,
                       virginia_law=_virginia_law_adapter(mode))

    server = build_server(ctx, profile="all")
    calls = []
    async with Client(server) as client:
        for tool, raw_args, note in DEMO_CALLS:
            args = {k: (sample_pin if v == "__SAMPLE_PIN__"
                        else no_match_pin if v == "__NO_MATCH_PIN__" else v)
                    for k, v in raw_args.items()}
            before = len(tracker.calls)
            result = await client.call_tool(tool, args)
            after = len(tracker.calls)
            calls.append({
                "note": note,
                "is_error": result.is_error,
                "envelope": result.structured_content,
                "error_text": (result.content[0].text
                               if result.is_error and result.content
                               else None),
                "http_calls": tracker.calls[before:after],
            })

    audit_records = [r.model_dump(mode="json") for r in ctx.audit.records]
    if len(audit_records) != len(calls):
        raise AssertionError(
            f"audit hook missed calls: {len(audit_records)} records for "
            f"{len(calls)} calls — the trail must cover every call")
    for call, record in zip(calls, audit_records):
        call["audit"] = record

    return {"generated_at": utc_now_iso(), "mode": mode,
            "call_count": len(calls),
            "fixture_recorded_at": recording["recorded_at"],
            "calls": calls}


def _virginia_law_adapter(mode: str):
    """The civic tool reads HTML pages, not ArcGIS, so it needs its own
    replay seam. Without this the 'fixtures' build would reach
    law.lis.virginia.gov for real and stop being deterministic."""
    from commonwealth.adapters.replay import HtmlReplayFetcher
    from commonwealth.adapters.virginia_law import VirginiaLawAdapter
    if mode != "fixtures":
        return VirginiaLawAdapter()
    base = "https://law.lis.virginia.gov/vacode"
    fixture_dir = FIXTURES_DIR / "va-code-of-virginia"
    pages = {
        f"{base}/1-500/": ((fixture_dir / "section-1-500.html").read_text(),
                           f"{base}/1-500/"),
        f"{base}/1-999999/": (
            (fixture_dir / "no-such-section.html").read_text(),
            f"{base}/title1/"),
    }
    return VirginiaLawAdapter(fetcher=HtmlReplayFetcher(pages))


INDEX_HTML = DOCS_DATA.parent / "index.html"


def embed_data(html: str, block_id: str, obj: dict) -> str:
    """Splice `obj` into `<script type="application/json" id="{block_id}">`
    in `html`, so the page reads embedded data instead of fetching it —
    fetch() rejects file:// URLs, so this is what makes index.html work
    opened directly (drag into a browser, email attachment), not just
    served over HTTP. `\\/`-escaping "</script" keeps a string value from
    ever prematurely closing the tag; it's valid JSON (`\\/` means `/`), so
    JSON.parse needs no matching change on the JS side.
    """
    text = json.dumps(obj, separators=(",", ":")).replace("</script", "<\\/script")
    pattern = (rf'(<script type="application/json" id="{block_id}">)'
               r'.*?(</script>)')
    new_html, n = re.subn(pattern, lambda m: m.group(1) + text + m.group(2),
                           html, count=1, flags=re.DOTALL)
    if n != 1:
        raise AssertionError(f"embed block #{block_id} not found in index.html")
    return new_html


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--fixtures", action="store_true",
                       help="deterministic run over recorded exchanges")
    group.add_argument("--live", action="store_true",
                       help="run against live services")
    args = ap.parse_args()
    mode = "fixtures" if args.fixtures else "live"

    from commonwealth.runtime import load_context

    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    catalog = build_catalog()
    demo = asyncio.run(run_demo(mode))
    resolver_demo = build_resolver_demo(load_context())

    (DOCS_DATA / "site.json").write_text(json.dumps(catalog, indent=1) + "\n")
    (DOCS_DATA / "audit-demo.json").write_text(
        json.dumps(demo, indent=1) + "\n")
    (DOCS_DATA / "resolver-demo.json").write_text(
        json.dumps(resolver_demo, indent=1) + "\n")

    html = INDEX_HTML.read_text()
    html = embed_data(html, "data-site", catalog)
    html = embed_data(html, "data-audit-demo", demo)
    html = embed_data(html, "data-resolver-demo", resolver_demo)
    INDEX_HTML.write_text(html)

    print(f"site.json: {catalog['counts']}")
    print(f"audit-demo.json: {demo['call_count']} calls ({mode})")
    print(f"resolver-demo.json: {len(resolver_demo['queries'])} queries")
    print(f"index.html: embedded 3 data blocks ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
