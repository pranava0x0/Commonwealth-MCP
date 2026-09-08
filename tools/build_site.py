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
    than one source (../design/architecture.md decision 0005-C) — the replay pool has to cover
    whichever ones actually get queried, not just Fairfax's."""
    exchanges: list[dict] = []
    for path in sorted(FIXTURES_DIR.glob("*/recorded.json")):
        exchanges.extend(json.loads(path.read_text())["exchanges"])
    return exchanges

# The only declared (not derived) rosters on the page, each shown with its
# status or cited against the spec text it paraphrases (checked below by
# WARNING_DEFINITIONS/COVERAGE_DEFINITIONS coverage asserts).
#
# Skills that exist are read off disk instead, by `skill_roster()` below.
# `parcel-zoning-screen` sat here as "planned" for two days after it
# shipped, which is the drift a typed roster produces.
PLANNED_SKILLS = [
    {"name": "legislative-impact-analysis", "status": "milestone 1b (civic)",
     "capabilities": [], "optional": [], "steps": [],
     "description": "Trace a bill to the Code sections it touches and the "
                    "localities it reaches. Waits on the legislative API "
                    "(GitHub issue #11)."},
    {"name": "development-site-due-diligence",
     "status": "deferred until there is coverage to justify it",
     "capabilities": [], "optional": [], "steps": [],
     "description": "One site, every registered layer, in one walk. Waits "
                    "on enough local coverage to be worth more than the "
                    "tools it would chain."},
]


def tool_parameters(spec) -> list[dict]:
    """The arguments a tool takes, read off the function the server binds.

    Read rather than declared, for the reason every other roster on this
    page is derived: a hand-typed argument list is a second place for the
    signature to live, and the second place is the one that goes stale.
    `ctx` is the runtime handle the server supplies, not something a
    caller passes, so it is not an argument of the tool.
    """
    import inspect

    sig = inspect.signature(spec.fn, eval_str=True)
    return [{"name": name,
             "required": param.default is inspect.Parameter.empty}
            for name, param in sig.parameters.items() if name != "ctx"]


def _frontmatter_of(path: Path) -> dict:
    import yaml

    text = path.read_text()
    if not text.startswith("---\n"):
        return {}
    return yaml.safe_load(text.split("---\n", 2)[1]) or {}


def _first_sentence(path: Path) -> str:
    """The skill's `description`, cut to its first sentence.

    A skill description is written for a model deciding whether to load
    the skill, so it opens by saying what the workflow does and then
    lists when to use it. The card wants the first half.
    """
    text = " ".join((_frontmatter_of(path).get("description") or "").split())
    head, _, _ = text.partition(". ")
    return (head + ".") if head and not head.endswith(".") else head


def _step_headings(path: Path) -> list[str]:
    """The `**Step N — ...**` headings a SKILL.md walks through.

    The walk is the thing a skill adds over its tools, so the card shows
    the steps rather than only the capabilities they need. Read off the
    file, so a re-ordered skill re-orders its card.
    """
    body = path.read_text().split("---\n", 2)[-1]
    steps = re.findall(r"^\*\*Step\s+([^\n*]+?)\.?\*\*", body, re.M)
    return [" ".join(s.split()) for s in steps]


def skill_roster() -> list[dict]:
    """Skills on disk, then the ones still declared as planned.

    A skill's capabilities come from its own frontmatter, so the page
    cannot claim a skill needs something the skill does not ask for.
    """
    from commonwealth.core.skills import load_skills

    shipped = [{"name": sk.name, "status": "shipped",
                "capabilities": list(sk.required_capabilities),
                "optional": list(sk.optional_capabilities),
                # The skill's own first sentence. Read off the file rather
                # than written here, so the card and the shipped skill
                # cannot describe the workflow differently.
                "description": _first_sentence(sk.path),
                "steps": _step_headings(sk.path)}
               for sk in load_skills(ROOT / "skills")]
    names = {sk["name"] for sk in shipped}
    return shipped + [sk for sk in PLANNED_SKILLS if sk["name"] not in names]

# design/provenance-envelope.md § 3 table, transcribed with the spec's own
# wording; a test asserts this covers every dimension value the models emit.
COVERAGE_DEFINITIONS = {
    "registry": {
        "question": "Does the Source Registry cover the requested "
                     "place/capability/time at all?",
        "values": {
            "covered": "A registered source should answer this.",
            "partial": "Some but not all of what was asked is covered.",
            "none": "No source is registered for this place. The answer "
                    "says so, and says which place it means.",
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
                          "short (ArcGIS exceededTransferLimit). The "
                          "answer is labelled as partial.",
            "unknown": "Paging completeness could not be determined.",
        },
    },
    "result": {
        "question": "Did anything match?",
        "values": {
            "hit": "At least one record matched.",
            "empty": "The search ran and matched nothing. That is a "
                      "result, and it is reported separately from a "
                      "failure.",
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
    "freshness_unavailable": "The publisher gives no machine-readable "
        "update date for this layer. The fetch time is known; how old the "
        "data itself is cannot be established.",
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

# The recorded trail the site walks through. One flat, ordered list: it
# was two lists spliced together (`DEMO_CALLS[5:5] = [...]`) because the
# boundary calls were added later, which put them in the middle of a
# narrative that had not been re-read. Order here is reading order.
#
# A test asserts every registered tool appears at least once
# (tests/test_site_data.py), so adding a tool without a demo fails CI
# rather than shipping a page that quietly covers less than it claims.
# Loudoun County, from a point in Sterling. The address the walk starts
# from is 21641 Ridgetop Cir, Sterling, VA 20166.
LOUDOUN = {"jurisdiction": "Loudoun County",
           "lon": -77.408014727372, "lat": 39.025534437083}

DEMO_CALLS = [
    # --- one place, every question (examples/one_address_every_question.py) ---
    ("registry.resolve_jurisdiction", {"query": "Sterling"},
     'Sterling does not resolve as a government name; use an address or coordinate.'),
    ("geo.resolve_location",
     {"address": "21641 Ridgetop Cir, Sterling, VA 20166"},
     'The Sterling mailing address resolves to Loudoun County.'),
    ("geo.find_parcel", dict(LOUDOUN),
     'No local parcel source is registered for Loudoun; VGIN returns a parcel.'),
    ("geo.find_zoning", dict(LOUDOUN),
     'No zoning source is registered for Loudoun County.'),
    ("geo.find_landmarks", dict(LOUDOUN),
     'The landmarks query returned no records within one kilometre.'),

    # --- whose government is this? ---
    ("registry.resolve_jurisdiction", {"query": "fairfax"},
     "Ambiguous on purpose: Fairfax City vs Fairfax County"),
    ("registry.resolve_jurisdiction", {"query": "Fairfax County"},
     "Exact resolution with the authority stack"),
    ("registry.resolve_jurisdiction", {"query": "Bedford City"},
     'The former Bedford City name resolves to Bedford town with a historical-name warning.'),
    ("registry.resolve_jurisdiction", {"lon": -77.3064, "lat": 38.8462},
     'This coordinate resolves to Fairfax City.'),
    ("registry.resolve_jurisdiction", {"lon": -77.2653, "lat": 38.9012},
     'This Vienna coordinate returns both town and county authorities.'),
    ("geo.resolve_location",
     {"address": "6800 Beulah St, Alexandria, VA 22310"},
     'The Alexandria mailing address resolves to Fairfax County.'),
    ("geo.resolve_location", {"zip_code": "24450"},
     'ZIP 24450 returns three locality candidates.'),

    # --- what is here? ---
    ("geo.find_parcel", {"jurisdiction": "Fairfax County",
                         "pin": "__SAMPLE_PIN__"},
     "Parcel record with evidence and provenance"),
    ("geo.find_zoning", {"jurisdiction": "Fairfax County",
                         "pin": "__SAMPLE_PIN__"},
     "Zoning via parcel-geometry intersection; screening warnings"),
    ("geo.find_address", {"jurisdiction": "Fairfax County",
                          "address": "4501 Carlby Ln"},
     'The address record has postal city ALEXANDRIA and locality Fairfax County.'),
    ("geo.find_buildings", {"jurisdiction": "Richmond City",
                            "pin": "C0010126019"},
     'Building footprints include the publisher area and an approximate projection correction.'),
    ("geo.find_roads", {"jurisdiction": "Vienna",
                        "street_name": "Center St"},
     'VDOT and VGIN return separate road records; one query is scoped to the county.'),
    ("geo.find_landmarks", {"jurisdiction": "Vienna",
                            "lon": -77.2653, "lat": 38.9012},
     'Landmark records identify their contributing agencies.'),
    ("geo.find_environmental_sites", {"jurisdiction": "Richmond City",
                                      "lon": -77.4360, "lat": 37.5407},
     'DEQ monitoring stations include sampling dates and coverage limits.'),
    ("geo.find_boundaries", {"jurisdiction": "Prince George County"},
     'The boundary lookup returns both published polygons for this FIPS code.'),
    ("civic.browse_code", {},
     'The Code of Virginia from the top. There is no full-text search '
     'over it from any public endpoint, so reaching a section you cannot '
     'cite means walking to it.'),
    ("civic.browse_code", {"title": "15.2"},
     'One title\u2019s chapters. Each row carries the arguments for the '
     'step below it.'),
    ("civic.browse_code", {"title": "15.2", "chapter": "22"},
     'The zoning chapter\u2019s sections. Each row carries the citation '
     'to read next.'),
    ("civic.browse_code", {"title": "99.9"},
     'A title the Code does not have. The publisher answers an unknown '
     'title and an empty one the same way, so the note says which '
     'question came back empty rather than guessing.'),
    ("civic.get_code_section", {"citation": "15.2-2200"},
     "The section the walk above ends at, read by citation \u2014 the two "
     "civic tools composing"),
    ("civic.get_code_section", {"citation": "1-500"},
     "Code of Virginia section text with its own citation history"),
    ("civic.get_code_section", {"citation": "1-999999"},
     'A section that does not exist. The site redirects rather than '
     '404ing, and the answer is found=False, not an error.'),

    # --- a town and its county, one piece of ground ---
    ("geo.find_zoning", {"jurisdiction": "Vienna",
                         "lon": -77.2653, "lat": 38.9012},
     "A point in a town. The town's zoning layer and the county's both "
     "cover this ground, so both answer, and the comparison block says "
     "whether they agree"),
    ("geo.find_zoning", {"jurisdiction": "Vienna", "pin": "0384 02  0143"},
     "The same ground by parcel number. The town publishes no parcel "
     "layer, so its districts are read over the county's parcel polygon, "
     "and the evidence names whose polygon that was"),
    ("geo.find_parcel", {"jurisdiction": "Leesburg", "pin": "231154488000"},
     "A town that publishes its own parcel layer, queried beside the "
     "statewide one"),
    ("geo.find_zoning", {"jurisdiction": "Leesburg", "pin": "231154488000"},
     "The town's own zoning map layer, with a link to the ordinance "
     "section returned as data"),

    # --- the four ways an answer comes back with no data ---
    ("geo.find_parcel", {"jurisdiction": "Fairfax County",
                         "pin": "__NO_MATCH_PIN__"},
     "A clean empty: covered registry, no record"),
    # VGIN's statewide layer (added 2026-08-28) covers parcel.lookup
    # everywhere in Virginia, so the remaining real gap for a
    # no-local-source county is zoning.lookup, not parcel.lookup.
    ("geo.find_zoning", {"jurisdiction": "Craig County", "pin": "123"},
     "A registry gap: coverage says none, not 'no results'"),
    ("geo.find_environmental_sites", {"jurisdiction": "Virginia",
                                      "lon": -74.5, "lat": 36.5},
     "An empty environmental answer, carrying the same disclaimer as a "
     "hit — 'no station on record here' is not 'nothing here'"),

    # --- large answers, and the handles that carry what does not fit ---
    ("geo.find_boundaries", {"jurisdiction": "Fairfax County",
                             "detail": "full"},
     "A boundary too large to return whole. The generalized rings come "
     "back inline and a commonwealth:// handle carries the publisher's "
     "own 16,641 vertices, with the expiry stated"),

    # --- what is registered at all? ---
    ("registry.search_sources", {"capability": "zoning.lookup"},
     "What covers zoning.lookup, with authority levels"),
    ("registry.describe_source",
     {"source_id": "va-deq-water-quality-stations"},
     'The source description includes access terms and an incomplete terms review.'),
    ("registry.source_status", {},
     "Declared vs operational state for every registered source"),
    ("registry.search_sources", {"capability": "unicorns.lookup"},
     'An unknown capability returns an InvalidQuery error.'),
]


def build_catalog() -> dict:
    import yaml
    from commonwealth import __version__
    from commonwealth.core import toolreg
    from commonwealth.core.envelope import (
        ExecutionCoverage, PaginationCoverage, RegistryCoverage,
        ResultCoverage, WarningCode,
    )
    from commonwealth.core.results import MemoryResultStore
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

    ctx = load_context(results=MemoryResultStore(deterministic=True))
    regs = registries()

    tools = []
    for package, reg in sorted(regs.items()):
        for spec in reg.tools():
            tools.append({"name": spec.name, "package": package,
                          "toolset": spec.toolset,
                          "contract_version": spec.contract_version,
                          "parameters": tool_parameters(spec),
                          "description": spec.description})

    # The clients `commonwealth configure` knows how to write, read off
    # that command's own table rather than typed onto the page. The site
    # told readers to hand-write a config block while the CLI had been
    # writing it correctly, with the absolute path filled in, all along.
    from commonwealth.cli import configure as cfg

    clients = [{"id": c.name, "scope": c.scope, "path": c.path,
                "format": "json", "note": c.note}
               for c in sorted(cfg.CLIENTS.values(), key=lambda c: c.name)]
    clients += [{"id": name, "scope": "user", "path": "", "format": "toml",
                 "note": "Keeps its MCP config in TOML; the command prints "
                         "the block to paste."}
                for name in sorted(cfg.TOML_CLIENTS)]

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
            # returns exactly one MCPServer (../design/architecture.md decision 0001, "one process").
            "servers": 1,
            "tools": len(tools),
            "packages": len(regs),
            "sources": len(sources),
            # A `proposed` manifest is inventory, not an endpoint
            # (design/source-registry.md § 6.3), so the page must never
            # present the registry total as the number of systems it can
            # actually query.
            "sources_active": sum(1 for s in sources
                                  if s["declared_state"] == "active"),
            "sources_proposed": sum(1 for s in sources
                                    if s["declared_state"] == "proposed"),
            "capabilities": len(ctx.sources.capability_vocab),
            "jurisdictions": len(ctx.jurisdictions),
            "trap_pairs": len(trap_pairs),
        },
        "tools": tools,
        "clients": clients,
        "sources": sources,
        "capabilities": sorted(ctx.sources.capability_vocab),
        "jurisdiction_kinds": dict(sorted(kinds.items())),
        "trap_pairs": [list(p) for p in trap_pairs],
        "profiles": profiles,
        "skills": skill_roster(),
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
        if res.matched_former_name:
            queries[key]["former_name"] = res.matched_former_name

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
        # A dissolved city's name is exactly what someone types out of an
        # old record, so the playground has to answer it.
        for f in j.former_names:
            record(f)
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
    from commonwealth.core.results import MemoryResultStore
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
    # A memory store, so a docs build leaves nothing in the developer's
    # cache and mints no machine-local handle. `geo.find_roads` in
    # DEMO_CALLS returns more records than the inline cap, so the disk
    # store would write a payload and bake a fresh random
    # `commonwealth://` id into committed site data on every rebuild —
    # a handle no reader of the published page could ever resolve.
    ctx = load_context(arcgis=adapter, geocoder=_geocoder(mode, tracker),
                       results=MemoryResultStore(deterministic=True),
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


def _geocoder(mode: str, tracker):
    """The locator is a different service shape from a FeatureServer, but
    it speaks the same JSON-over-GET, so it replays through the same
    tracked fetcher — which is what puts its outbound request in the
    page's HTTP view alongside the ArcGIS ones."""
    from commonwealth.adapters.arcgis_geocode import ArcGISGeocodeAdapter
    from commonwealth.adapters.base import TTLCache
    # The tracker in BOTH modes. Its live branch builds a per-host
    # HttpFetcher, so an untracked adapter here bought nothing and cost
    # the page its honesty: a --live build presented http_calls as the
    # real outbound trail while the locator's request was missing from it.
    del mode
    return ArcGISGeocodeAdapter(fetcher=tracker, cache=TTLCache())


def _virginia_law_adapter(mode: str):
    """The civic tool reads HTML pages, not ArcGIS, so it needs its own
    replay seam. Without this the 'fixtures' build would reach
    law.lis.virginia.gov for real and stop being deterministic."""
    from commonwealth.adapters.replay import HtmlReplayFetcher, ReplayFetcher
    from commonwealth.adapters.virginia_law import VirginiaLawAdapter
    from commonwealth.fixtures import (recorded_api_exchanges,
                                       recorded_pages)
    if mode != "fixtures":
        return VirginiaLawAdapter()
    # The same two seams the tests replay, from the same two functions.
    # This built its own copy of the page list, so a page recorded for the
    # tests was not a page the site build could reach, and adding one to
    # both was a step nobody would remember twice.
    return VirginiaLawAdapter(fetcher=HtmlReplayFetcher(recorded_pages()),
                              json_fetcher=ReplayFetcher(
                                  recorded_api_exchanges()))


SITE_URL = "https://pranava0x0.github.io/Commonwealth-MCP/"
REPO_URL = "https://github.com/pranava0x0/Commonwealth-MCP"


def structured_data(catalog: dict) -> dict:
    """schema.org JSON-LD, so a crawler reads this as software.

    Issue #40 is about being findable, and the registry listing is only
    half of that. Every value here is derived from the same catalog the
    page renders, so the description a search engine reads cannot drift
    from the one a reader sees.
    """
    c = catalog["counts"]
    return {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebSite", "@id": SITE_URL + "#website",
             "url": SITE_URL, "name": "Commonwealth-MCP",
             "about": {"@id": SITE_URL + "#software"}},
            {"@type": "SoftwareSourceCode", "@id": SITE_URL + "#software",
             "name": "Commonwealth-MCP", "url": SITE_URL,
             "codeRepository": REPO_URL,
             "license": "https://www.apache.org/licenses/LICENSE-2.0",
             "programmingLanguage": "Python",
             "softwareVersion": catalog["version"],
             "applicationCategory": "DeveloperApplication",
             "description":
                 f"An MCP server for Virginia state and local public data: "
                 f"{c['tools']} tools over {c['sources_active']} registered "
                 f"government systems, covering parcels, zoning, "
                 f"jurisdiction boundaries, addresses, buildings, roads, "
                 f"landmarks, monitored environmental sites and the Code of "
                 f"Virginia. Every answer carries its sources, retrieval "
                 f"dates and coverage, and every one of Virginia's "
                 f"{c['jurisdictions']} governments is in its jurisdiction "
                 f"table.",
             "keywords": ["mcp", "model-context-protocol", "virginia",
                          "civic-tech", "gis", "open-data", "public-data",
                          "arcgis", "parcels", "zoning",
                          "code-of-virginia"]},
        ],
    }


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
    # Either JSON mime type: the catalog blocks are `application/json`
    # and the structured-data block is `application/ld+json`, and both are
    # spliced the same way.
    pattern = (rf'(<script type="application/(?:ld\+)?json" '
               rf'id="{block_id}">)'
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

    from commonwealth.core.results import MemoryResultStore
    from commonwealth.runtime import load_context

    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    catalog = build_catalog()
    demo = asyncio.run(run_demo(mode))
    resolver_demo = build_resolver_demo(
        load_context(results=MemoryResultStore(deterministic=True)))

    (DOCS_DATA / "site.json").write_text(json.dumps(catalog, indent=1) + "\n")
    (DOCS_DATA / "audit-demo.json").write_text(
        json.dumps(demo, indent=1) + "\n")
    (DOCS_DATA / "resolver-demo.json").write_text(
        json.dumps(resolver_demo, indent=1) + "\n")

    html = INDEX_HTML.read_text()
    html = embed_data(html, "data-jsonld", structured_data(catalog))
    html = embed_data(html, "data-site", catalog)
    html = embed_data(html, "data-audit-demo", demo)
    html = embed_data(html, "data-resolver-demo", resolver_demo)
    INDEX_HTML.write_text(html)

    print(f"site.json: {catalog['counts']}")
    print(f"audit-demo.json: {demo['call_count']} calls ({mode})")
    print(f"resolver-demo.json: {len(resolver_demo['queries'])} queries")
    print(f"index.html: embedded 4 data blocks ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
