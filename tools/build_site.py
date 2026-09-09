#!/usr/bin/env python3
"""Generate the docs site's data: catalog counts and the audit-trail demo.

Everything the page displays derives from the live registries and a real
run through the MCP layer — no hand-typed counts anywhere (the one
exception, PLANNED_SKILLS, is a declared roster with its status stated).

  .venv/bin/python tools/build_site.py --fixtures   # deterministic, offline
  .venv/bin/python tools/build_site.py --live       # against live services

Outputs docs/data/*.json and embeds the small ones into the four
pages under docs/.
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
# The skills live inside the plugin bundle that installs them
# alongside the server (GitHub issue #53); the wheel copies this
# same directory in, so there is one copy to go stale.
PLUGIN_DIR = ROOT / "plugins" / "commonwealth-mcp"
SKILLS_DIR = PLUGIN_DIR / "skills"
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


def _lead_sentence(text: str) -> str:
    """The first sentence of `text`, for a card or a row that shows one line.

    A sentence ends at a full stop followed by a capital, not at every
    ". " — a tool description reading "by its citation (e.g. '1-500')"
    would otherwise be cut after "e.g." and advertise nothing.
    """
    flat = " ".join((text or "").split())
    head = re.split(r"(?<=[.!?])\s+(?=[A-Z])", flat, maxsplit=1)[0]
    return head


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
                # What to type to run it. In the skill's own frontmatter
                # rather than on the page, so a new skill arrives with its
                # prompt and the card cannot offer one for a walk that
                # changed underneath it.
                "prompt": " ".join(((_frontmatter_of(sk.path).get("metadata")
                                     or {}).get("commonwealth") or {})
                                   .get("example_prompt", "").split()),
                "steps": _step_headings(sk.path)}
               for sk in load_skills(SKILLS_DIR)]
    names = {sk["name"] for sk in shipped}
    return shipped + [sk for sk in PLANNED_SKILLS if sk["name"] not in names]

# A capability id is a wire name. It says nothing to a reader who has not
# read the registry spec, so every place the site shows one it shows this
# instead: the question the capability answers, and the one-word subject
# that labels a filter chip or a source card. build_catalog() asserts this
# covers the live capability vocabulary, so a new capability fails the
# build rather than rendering as a bare id.
CAPABILITY_COPY = {
    "address.lookup": ("What is at this address?", "addresses"),
    "boundary.lookup": ("Where does this jurisdiction end?", "boundaries"),
    "building.lookup": ("Is this ground built on?", "buildings"),
    "code_section.lookup": ("What does this section of the Code say?",
                           "Code sections"),
    "code_structure.browse": ("How is the Code of Virginia organised?",
                              "the Code's contents"),
    "environmental_site.lookup": ("Is anything monitored near here?",
                                  "monitored sites"),
    "geocode.address": ("Where is this address, and whose government is it?",
                        "geocoding"),
    "landmark.lookup": ("Which schools, libraries, or fire stations are "
                        "nearby?", "public places"),
    "parcel.lookup": ("What is this parcel?", "parcels"),
    "road.lookup": ("What roads are here, and what are they called?",
                    "roads"),
    "zoning.lookup": ("How is this zoned?", "zoning"),
}

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

DEMO_GROUPS = [
    ('One address, every question',
     'One mailing address in Sterling, asked five ways. It is the '
     'walk that produces a found record, a registry gap, and an '
     'empty result in a row.', [
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
    ]),

    ('Whose government is this?',
     'Names that match two governments, a name that no longer '
     'exists, a ZIP that crosses three localities, and a postal city '
     'that is not the government.', [
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
    ]),

    ('What is on this ground?',
     'One call per subject: parcels, zoning, addresses, buildings, '
     'roads, public places, monitored sites, boundaries, and the '
     'Code of Virginia.', [
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
    ]),

    ('A town and its county, one piece of ground',
     'Vienna and Leesburg sit inside counties that publish the same '
     'layers. Both answer, unranked, and the comparison says whether '
     'they agree.', [
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
    ]),

    ('The ways an answer comes back with no data',
     'A search that matched nothing, a place with no registered '
     'source, and an empty environmental answer that still carries '
     'its disclaimer.', [
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
    ]),

    ('An answer too large to return inline',
     'The generalized rings come back in the envelope and a '
     "commonwealth:// handle carries the publisher's full geometry.", [
        ("geo.find_boundaries", {"jurisdiction": "Fairfax County",
                                 "detail": "full"},
         "A boundary too large to return whole. The generalized rings come "
         "back inline and a commonwealth:// handle carries the publisher's "
         "own 16,641 vertices, with the expiry stated"),
    ]),

    ('What is registered at all?',
     'The registry answering about itself: what covers a capability, '
     'what a manifest says, whether each source is up, and what an '
     'unknown capability returns.', [
        ("registry.search_sources", {"capability": "zoning.lookup"},
         "What covers zoning.lookup, with authority levels"),
        ("registry.describe_source",
         {"source_id": "va-deq-water-quality-stations"},
         'The source description includes access terms and an incomplete terms review.'),
        ("registry.source_status", {},
         "Declared vs operational state for every registered source"),
        ("registry.search_sources", {"capability": "unicorns.lookup"},
         'An unknown capability returns an InvalidQuery error.'),
    ]),

]

# The flat, ordered trail. The groups above are the reading order;
# this is what the audit run walks and what the tests index into.
DEMO_CALLS = [c for _, _, calls in DEMO_GROUPS for c in calls]


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

    missing = set(ctx.sources.capability_vocab) - set(CAPABILITY_COPY)
    extra = set(CAPABILITY_COPY) - set(ctx.sources.capability_vocab)
    if missing or extra:
        raise AssertionError(
            "CAPABILITY_COPY drifted from the capability vocabulary: "
            f"missing={sorted(missing)} extra={sorted(extra)}")

    tools = []
    for package, reg in sorted(regs.items()):
        for spec in reg.tools():
            tools.append({"name": spec.name, "package": package,
                          "toolset": spec.toolset,
                          "contract_version": spec.contract_version,
                          "parameters": tool_parameters(spec),
                          # The row a reader scans is one sentence; the
                          # rest of the description opens on demand. Cut
                          # from the docstring rather than written here,
                          # so the summary cannot describe a tool the
                          # server does not have.
                          "summary": _lead_sentence(spec.description),
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

    def jurisdiction_name(jid: str) -> str:
        j = ctx.jurisdictions.get(jid)
        return j.name if j else jid

    sources = []
    for m in sorted(ctx.sources.manifests.values(), key=lambda m: m.id):
        caps = sorted(m.capability_ids())
        sources.append({
            "id": m.id, "name": m.name, "jurisdiction": m.jurisdiction,
            # The place as a reader would name it. A card headed
            # `va:charles-city-county` makes the reader decode the id
            # before they can tell whether the source is near them.
            "jurisdiction_name": ("Virginia, statewide" if m.jurisdiction == "va"
                                  else jurisdiction_name(m.jurisdiction)),
            # What it answers, in the words the questions above use.
            "answers": [CAPABILITY_COPY[c][1] for c in caps],
            "publisher": m.publisher.agency,
            "authority_level": m.publisher.authority_level.value,
            "capabilities": caps,
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

    # The tool names in each profile, not just how many. The tools page
    # shows the default profile first and holds the rest behind a button,
    # which needs to know which tools those are.
    profiles = {name: [spec.name for spec in toolreg.expand_profile(name, regs)]
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
        "capability_copy": {cap: {"question": CAPABILITY_COPY[cap][0],
                                  "subject": CAPABILITY_COPY[cap][1]}
                            for cap in sorted(ctx.sources.capability_vocab)},
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
    calls: list[dict] = []
    # Where each walk starts and how long it runs, so the trail page can
    # head each run of cards with what that run demonstrates. Spans rather
    # than nested lists: the flat `calls` list stays the trail, which is
    # what the audit hook, the tests and every `#call-N` link index into.
    groups = []
    async with Client(server) as client:
        for title, group_note, group_calls in DEMO_GROUPS:
            groups.append({"title": title, "note": group_note,
                           "first": len(calls), "count": len(group_calls)})
            for tool, raw_args, note in group_calls:
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
            "groups": groups,
            "calls": calls}


# The one walk the landing page shows without a click: a mailing address
# in Sterling, then the three questions asked about the point it resolves
# to. It is the walk chosen because those three answers come back three
# different ways — a record found, no source registered, and a search that
# matched nothing — which is the distinction the whole project turns on.
FEATURED_WALK = ("One address, every question",
                 "21641 Ridgetop Cir, Sterling, VA 20166",
                 ("geo.resolve_location", "geo.find_parcel",
                  "geo.find_zoning", "geo.find_landmarks"))


def featured_walk(demo: dict) -> dict:
    """The landing page's four steps, picked out of the recorded trail.

    Only the fields a step badge needs travel with it, so the landing
    page carries about a kilobyte rather than four full envelopes. Each
    step keeps its index in the trail, which is what `examples.html#call-N`
    links to for the answer itself.
    """
    title, address, tools = FEATURED_WALK
    group = next(g for g in demo["groups"] if g["title"] == title)
    span = range(group["first"], group["first"] + group["count"])
    steps = []
    for tool in tools:
        idx = next((i for i in span
                    if demo["calls"][i]["audit"]["tool"] == tool), None)
        if idx is None:
            raise AssertionError(
                f"featured walk names {tool!r}, which the {title!r} group "
                "does not call — the trail and the landing page have drifted")
        a = demo["calls"][idx]["audit"]
        steps.append({"index": idx, "tool": tool,
                      "note": demo["calls"][idx]["note"],
                      "coverage": a["coverage"],
                      "warning_codes": a["warning_codes"],
                      "requires_user_choice": a["requires_user_choice"],
                      "error": a["error"]})
    return {"title": title, "address": address, "steps": steps}


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


def plugin_bundle() -> dict:
    """What the quick start's install step says, read off the manifests.

    The marketplace name, the plugin name and the skill count are three
    numbers a page can state wrongly, and the reader finds out by typing a
    command that fails. Read from the files a client would read.
    """
    marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text())
    manifest = json.loads(
        (PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text())
    return {
        "name": manifest["name"],
        "marketplace_name": marketplace["name"],
        # What `/plugin marketplace add` takes: the GitHub owner and repo,
        # from the repository this plugin declares.
        "marketplace": REPO_URL.removeprefix("https://github.com/"),
        "path": str(PLUGIN_DIR.relative_to(ROOT)),
        "skill_count": len(list(SKILLS_DIR.glob("*/SKILL.md"))),
    }


def doctor_output() -> str:
    """What `commonwealth doctor` prints, captured by running it.

    The quick start shows this so a reader can tell a healthy first run
    from a broken one before they have one. Run rather than transcribed:
    a pasted sample goes stale the first time a manifest is added, and
    the counts in it are exactly the ones that move. The offline run is
    captured; `--live` adds a probe line per source and needs a network.
    """
    import contextlib
    import io

    from commonwealth.cli.__main__ import cmd_doctor

    buf = io.StringIO()
    args = argparse.Namespace(live=False)
    with contextlib.redirect_stdout(buf):
        code = cmd_doctor(args)
    if code != 0:
        raise AssertionError(
            "`commonwealth doctor` reports problems in this checkout; "
            "fix them rather than publishing the output:\n" + buf.getvalue())
    return buf.getvalue().rstrip("\n")


# What to type once a client is connected. Each one is filled in from a
# call that is actually on the recorded trail, so a reader who copies a
# prompt can read the answer it produced before running anything, and a
# prompt naming a parcel or a citation the demo no longer uses fails the
# build instead of shipping.
STARTER_PROMPTS = [
    ("geo.resolve_location", ("address",),
     "Whose government covers {address}? Then tell me the parcel and the "
     "zoning at that point."),
    ("geo.find_zoning", ("jurisdiction", "pin"),
     "How is parcel {pin} in {jurisdiction} zoned, and what does the "
     "answer not establish?"),
    ("civic.get_code_section", ("citation",),
     "What does § {citation} of the Code of Virginia say?"),
]


def starter_prompts(demo: dict) -> list[dict]:
    """The quick start's prompts, each bound to the call that answers it."""
    out = []
    for tool, fields, template in STARTER_PROMPTS:
        idx = next((i for i, c in enumerate(demo["calls"])
                    if c["audit"]["tool"] == tool
                    and all((c["audit"].get("args") or {}).get(f)
                            for f in fields)), None)
        if idx is None:
            raise AssertionError(
                f"no recorded call of {tool} carries {list(fields)}; the "
                "starter prompt has no answer to point at")
        args = demo["calls"][idx]["audit"]["args"]
        out.append({"text": template.format(**{f: args[f] for f in fields}),
                    "tool": tool, "call": idx})
    return out


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


DOCS = DOCS_DATA.parent
# Every page the build writes into. Each one carries the small `data-core`
# block and fetches the large files it needs; index.html carries the
# structured data and the featured walk as well.
PAGES = ("index.html", "tools.html", "sources.html", "examples.html")


def embed_data(html: str, block_id: str, obj: dict, page: str) -> str:
    """Splice `obj` into `<script type="application/json" id="{block_id}">`.

    Only the small blocks are spliced. The three large files
    (`coverage.json`, `audit-demo.json`, `resolver-demo.json`) are fetched
    by the page that needs them, which is why opening a page from disk now
    shows a note asking for `python -m http.server -d docs` rather than the
    trail: fetch() rejects file:// URLs. `\\/`-escaping "</script" keeps a
    string value from ever prematurely closing the tag; it's valid JSON
    (`\\/` means `/`), so JSON.parse needs no matching change on the JS
    side.
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
        raise AssertionError(f"embed block #{block_id} not found in {page}")
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

    # The catalog splits in two. `core` is what every page needs to draw
    # its first screen and is embedded in all four; `coverage` is the
    # per-jurisdiction detail — 88% of the catalog's bytes — and is fetched
    # by the two views that show it (GitHub issue #52).
    coverage = {k: catalog.pop(k)
                for k in ("jurisdictions", "capability_coverage")}
    catalog["featured"] = featured_walk(demo)
    catalog["starter_prompts"] = starter_prompts(demo)
    catalog["doctor_output"] = doctor_output()
    catalog["plugin"] = plugin_bundle()
    catalog["demo_meta"] = {k: demo[k] for k in
                            ("generated_at", "mode", "call_count",
                             "fixture_recorded_at")}

    (DOCS_DATA / "core.json").write_text(json.dumps(catalog, indent=1) + "\n")
    (DOCS_DATA / "coverage.json").write_text(
        json.dumps(coverage, indent=1) + "\n")
    (DOCS_DATA / "audit-demo.json").write_text(
        json.dumps(demo, indent=1) + "\n")
    (DOCS_DATA / "resolver-demo.json").write_text(
        json.dumps(resolver_demo, indent=1) + "\n")

    for page in PAGES:
        path = DOCS / page
        html = embed_data(path.read_text(), "data-core", catalog, page)
        if page == "index.html":
            html = embed_data(html, "data-jsonld",
                              structured_data(catalog), page)
        path.write_text(html)
        print(f"{page}: {len(html)} bytes")

    print(f"core.json: {catalog['counts']}")
    print(f"coverage.json: {len(coverage['capability_coverage'])} capabilities "
          f"over {len(coverage['jurisdictions'])} jurisdictions")
    print(f"audit-demo.json: {demo['call_count']} calls in "
          f"{len(demo['groups'])} walks ({mode})")
    print(f"resolver-demo.json: {len(resolver_demo['queries'])} queries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
