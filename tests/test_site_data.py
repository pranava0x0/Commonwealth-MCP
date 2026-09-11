"""The docs site's baked data stays derived: committed JSON must match what
the live registries produce, and every demo envelope must validate against
the committed wire schema (generated output commits with its source)."""
import json
import re
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SKILLS_SRC = ROOT / "plugins" / "commonwealth-mcp" / "skills"
# The catalog splits in two so a page loads only what it draws (issue #52):
# `core` is embedded in all four pages, `coverage` is fetched by the two
# views that show it. The `site` fixture puts them back together, which is
# what build_catalog() returns and what every assertion here reads.
CORE = DOCS / "data" / "core.json"
COVERAGE = DOCS / "data" / "coverage.json"
DEMO = DOCS / "data" / "audit-demo.json"
RESOLVER = DOCS / "data" / "resolver-demo.json"
REGEN = "regenerate: .venv/bin/python tools/build_site.py --fixtures"

# Every page the build writes, and which section of the site each holds.
PAGES = ("index.html", "tools.html", "sources.html", "examples.html",
         "demos.html")


@pytest.fixture(scope="module")
def core() -> dict:
    assert CORE.exists(), f"missing {CORE}; {REGEN}"
    return json.loads(CORE.read_text())


@pytest.fixture(scope="module")
def site(core) -> dict:
    assert COVERAGE.exists(), f"missing {COVERAGE}; {REGEN}"
    return {**core, **json.loads(COVERAGE.read_text())}


@pytest.fixture(scope="module")
def demo() -> dict:
    assert DEMO.exists(), f"missing {DEMO}; {REGEN}"
    return json.loads(DEMO.read_text())


@pytest.fixture(scope="module")
def resolver_demo() -> dict:
    assert RESOLVER.exists(), f"missing {RESOLVER}; {REGEN}"
    return json.loads(RESOLVER.read_text())


def test_site_counts_match_live_registries(site):
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from build_site import build_catalog
    current = build_catalog()
    assert site["counts"] == current["counts"], REGEN
    assert [t["name"] for t in site["tools"]] == \
           [t["name"] for t in current["tools"]], REGEN
    assert site["capabilities"] == current["capabilities"], REGEN
    assert site["capability_coverage"] == current["capability_coverage"], REGEN
    print(f"catalog counts verified against live registries: "
          f"{site['counts']}")


def test_demo_trail_covers_every_call(demo):
    calls = demo["calls"]
    assert demo["call_count"] == len(calls) and len(calls) >= 8
    for c in calls:
        assert "audit" in c, "a call without an audit record broke the trail"
        assert c["audit"]["tool"]
        if c["audit"]["args"] is not None:
            assert None not in c["audit"]["args"].values(), (
                "null default args are noise; the audit record drops them")
    errors = [c for c in calls if c["is_error"]]
    assert len(errors) == 1 and "InvalidQuery" in errors[0]["error_text"]
    print(f"audit demo: {len(calls)} calls, 1 typed error, mode "
          f"{demo['mode']}")


def test_the_demo_trail_exercises_every_registered_tool(demo):
    """The page says these calls are what the server does. A tool with no
    call on the page is a tool the page silently does not demonstrate,
    and for six of them that was true for a while — the trail was written
    when the server had eight tools and nothing failed when it reached
    fourteen.

    Derived from the tool registry, per the structural rule in
    design/testing-and-demos.md § 4: never a hand-typed list."""
    from commonwealth.core import toolreg
    from commonwealth.servers.build import registries

    registered = {s.name for s in toolreg.expand_profile("all", registries())}
    assert registered, "no tools registered — the derivation basis vanished"
    demonstrated = {c["audit"]["tool"] for c in demo["calls"]}
    missing = sorted(registered - demonstrated)
    assert missing == [], (
        f"tools with no demo call: {missing} — add one to DEMO_CALLS in "
        "tools/build_site.py and rebuild")
    stale = sorted(demonstrated - registered)
    assert stale == [], f"demo calls for tools that no longer exist: {stale}"
    print(f"demo trail exercises {len(registered)} registered tools")


def test_the_demo_trail_shows_every_way_an_answer_comes_back_empty(demo):
    """The page's claim is that an empty answer means different things
    and says which. That claim needs one call per shape on the page: a
    covered search that matched nothing, a registry gap, and an ambiguity
    the tool refused to resolve."""
    shapes = set()
    for c in demo["calls"]:
        env = c["envelope"] or {}
        cov = env.get("coverage") or {}
        if c["is_error"]:
            shapes.add("typed_error")
        elif env.get("requires_user_choice"):
            shapes.add("requires_user_choice")
        elif cov.get("result") == "empty":
            shapes.add("gap" if cov.get("registry") == "none" else "no_match")
    assert shapes == {"typed_error", "requires_user_choice", "gap",
                      "no_match"}, sorted(shapes)


def test_demo_envelopes_validate_against_committed_schema(demo,
                                                          project_root):
    schema = json.loads(
        (project_root / "schemas" / "envelope.schema.json").read_text())
    checked = 0
    for c in demo["calls"]:
        if c["is_error"]:
            continue
        jsonschema.validate(c["envelope"], schema)
        checked += 1
    assert checked >= 7, f"only {checked} envelopes checked"
    print(f"validated {checked} demo envelopes against the wire schema")


def test_demo_shows_the_three_distinct_empties(demo):
    """The page's whole argument: a hit, a clean empty, and a registry gap
    must be visibly different in the baked data."""
    by_note = {c["note"]: c for c in demo["calls"]}
    clean_empty = by_note["A clean empty: covered registry, no record"]
    gap = by_note["A registry gap: coverage says none, not 'no results'"]
    assert clean_empty["envelope"]["coverage"]["registry"] == "covered"
    assert clean_empty["envelope"]["coverage"]["result"] == "empty"
    assert gap["envelope"]["coverage"]["registry"] == "none"


def test_every_page_embeds_the_core_block_and_fetches_the_rest(core):
    """The four pages carry one small block inline and name the files they
    fetch. Inlining all of it was 1.25 MB in one request (issue #52); the
    trade is that a page opened straight off disk shows a note instead of
    the trail, and `python -m http.server -d docs` is the documented fix."""
    fetched = {"coverage", "audit-demo", "resolver-demo"}
    for page in PAGES:
        html = (DOCS / page).read_text()
        m = re.search(
            r'<script type="application/json" id="data-core">(.*?)</script>',
            html, re.DOTALL)
        assert m, f"{page}: missing embedded data block #data-core"
        assert json.loads(m.group(1)) == core, (
            f"{page}: embedded #data-core does not match docs/data/ — {REGEN}")
        assert "hand-typed" not in html  # the page renders, it never restates
        for key in ("jurisdictions", "capability_coverage"):
            assert key not in core, (
                f"{key} belongs in coverage.json; embedding it puts "
                "88% of the catalog's bytes back into every page")
    js = (DOCS / "assets" / "site.js").read_text()
    for name in fetched:
        assert f'"{name}"' in js, (
            f"nothing on the site loads data/{name}.json, so the committed "
            "file is dead weight")
    for name in fetched:
        assert (DOCS / "data" / f"{name}.json").exists(), \
            f"the site fetches data/{name}.json and it is not committed"


def test_the_pages_share_one_nav_and_one_footer():
    """The nav and the footer are hand-written in every page file rather
    than rendered, so that a reader without JavaScript still has both.
    This is the cost of that choice: a link added to one page and not the
    others fails here instead of shipping as a page that quietly leads
    nowhere."""
    def block(html, start, end):
        return html[html.index(start):html.index(end) + len(end)]

    navs, feet = set(), set()
    for page in PAGES:
        html = (DOCS / page).read_text()
        # aria-current marks the page you are on; it is the one difference.
        navs.add(block(html, '<nav class="toc">', "</nav>")
                 .replace(' aria-current="page"', ""))
        feet.add(block(html, "<footer>", "</footer>"))
    assert len(navs) == 1, "the pages do not share one nav"
    assert len(feet) == 1, "the pages do not share one footer"
    for page in PAGES:
        html = (DOCS / page).read_text()
        assert html.count('aria-current="page"') == 1, (
            f"{page}: exactly one nav link marks the current page")


def test_the_page_that_holds_each_section_is_the_one_the_nav_points_at():
    """Issue #46 moved four sections onto three pages. A stranger's
    bookmark of `#tools` and llms.txt's link to it still have to land on
    the tools, which is what MOVED_ANCHORS in site.js is for."""
    js = (DOCS / "assets" / "site.js").read_text()
    for anchor, target in (("tools", "tools.html"), ("sources", "sources.html"),
                           ("examples", "examples.html"),
                           ("try", "examples.html")):
        assert f'{anchor}: "{target}' in js, (
            f"#{anchor} used to name a section of the one-page site and "
            f"nothing redirects it to {target}")
    for page, marker in (("tools.html", 'id="tool-results"'),
                         ("sources.html", 'id="sources-cards"'),
                         ("examples.html", 'id="calls"')):
        assert marker in (DOCS / page).read_text(), \
            f"{page} does not hold the section the nav sends readers to"


def test_demo_calls_that_hit_the_source_show_the_real_http_exchange(demo):
    """The two calls with zoning/parcel geometry work must show the actual
    ArcGIS URLs and record counts a visitor could hit themselves — not a
    paraphrase of the tool call."""
    by_note = {c["note"]: c for c in demo["calls"]}
    zoning = by_note["Zoning via parcel-geometry intersection; "
                      "screening warnings"]
    assert zoning["http_calls"], "zoning lookup made no tracked HTTP calls"
    for hc in zoning["http_calls"]:
        assert hc["url"].startswith("https://www.fairfaxcounty.gov/")
        assert "response" in hc and "params" in hc
    no_source_calls = ["Ambiguous on purpose: Fairfax City vs Fairfax "
                        "County", "A registry gap: coverage says none, "
                        "not 'no results'"]
    for note in no_source_calls:
        assert by_note[note]["http_calls"] == [], (
            f"{note!r} should need no outbound call — it never reaches a "
            "source, and the demo should say so by showing none")


def test_resolver_demo_matches_the_live_resolver(resolver_demo):
    """Every precomputed answer in the playground must still be what the
    real JurisdictionTable.resolve() returns today — this is the guard
    against the playground silently drifting from the tool it mirrors."""
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from build_site import build_resolver_demo
    from commonwealth.runtime import load_context

    current = build_resolver_demo(load_context())
    assert resolver_demo == current, REGEN
    assert len(resolver_demo["queries"]) >= 50
    # the trap pairs must show up as ambiguous, not silently resolved
    for stem in ("fairfax", "richmond", "roanoke", "franklin"):
        entry = resolver_demo["queries"][stem]
        assert entry["resolved"] is None and len(entry["candidates"]) == 2, (
            f"{stem!r} is a known name collision; the playground must "
            "show candidates, never guess")
    print(f"resolver playground: {len(resolver_demo['queries'])} queries, "
          "verified against the live resolver")


def test_coverage_and_warning_definitions_cover_every_enum_value(site):
    from commonwealth.core.envelope import (
        ExecutionCoverage, PaginationCoverage, RegistryCoverage,
        ResultCoverage, WarningCode,
    )
    assert set(site["warning_definitions"]) == {c.value for c in WarningCode}
    dims = {"registry": RegistryCoverage, "execution": ExecutionCoverage,
            "pagination": PaginationCoverage, "result": ResultCoverage}
    for dim, enum_cls in dims.items():
        assert set(site["coverage_definitions"][dim]["values"]) == \
            {c.value for c in enum_cls}


# --- typed numbers in reader-facing prose ---------------------------------

READER_FACING = ("README.md", "docs/llms.txt", "docs/index.html",
                 "docs/tools.html", "docs/sources.html", "docs/examples.html",
                 "src/commonwealth/domains/registry.py")


def _jurisdiction_counts() -> dict[str, int]:
    import yaml
    from collections import Counter
    kinds = Counter(
        yaml.safe_load(path.read_text())["kind"]
        for path in (ROOT / "sources" / "jurisdictions").glob("*.yaml"))
    return {"towns": kinds["town"],
            "localities": kinds["county"] + kinds["independent-city"]}


def test_no_reader_facing_page_states_a_town_count_the_table_denies():
    """The 191/189 drift, pinned (2026-09-01).

    VGIN publishes 191 town polygons and two of them are Census
    Designated Places with no government. Both were removed from the table
    on 2026-08-30 with a test pinning their absence, and the README, the
    site, and the jurisdiction spec went on saying 191 for two more days —
    a coverage claim, in the three places a stranger reads first.

    Derived from the table so the number cannot be typed wrong again. Any
    other count of towns in these files fails, including a future one that
    is right today and stale next month.
    """
    counts = _jurisdiction_counts()
    assert counts["towns"] and counts["localities"], "the table vanished"
    pattern = re.compile(r"(\d[\d,]*)\s+(?:incorporated\s+)?towns?\b")
    wrong = []
    for name in READER_FACING:
        text = (ROOT / name).read_text()
        for match in pattern.finditer(text):
            stated = int(match.group(1).replace(",", ""))
            if stated != counts["towns"]:
                line = text[:match.start()].count("\n") + 1
                wrong.append(f"{name}:{line} says {stated}")
    assert wrong == [], (
        f"the table holds {counts['towns']} towns; " + "; ".join(wrong))


def test_every_shipped_skill_is_named_on_the_reader_facing_pages():
    """`docs/llms.txt` is hand-written and it is what an assistant reads
    instead of the page, so it drifts silently. It claimed no geocoder was
    registered for three days after one was. Derived from disk so a fourth
    skill has to be mentioned rather than remembered."""
    from commonwealth.core.skills import load_skills

    text = (ROOT / "docs" / "llms.txt").read_text()
    missing = [sk.name for sk in load_skills(SKILLS_SRC)
               if sk.name not in text]
    assert missing == [], (
        f"docs/llms.txt does not mention {missing}; it is the summary an "
        "assistant reads, and a skill it omits does not exist as far as "
        "that reader is concerned")


def test_the_site_does_not_call_a_shipped_skill_planned(site):
    """`parcel-zoning-screen` sat in the page's roster as "planned" for two
    days after it shipped, because the roster was typed. It is read off
    disk now, and this asserts the two agree."""
    from commonwealth.core.skills import load_skills

    on_disk = {sk.name for sk in load_skills(SKILLS_SRC)}
    listed = {sk["name"]: sk["status"] for sk in site["skills"]}
    for name in on_disk:
        assert listed.get(name) == "shipped", (
            f"{name} exists on disk and the page says {listed.get(name)!r}; "
            + REGEN)
    for name, status in listed.items():
        if name not in on_disk:
            assert status != "shipped", (
                f"the page calls {name} shipped and there is no "
                f"{SKILLS_SRC.relative_to(ROOT)}/{name}/SKILL.md")


# --- the demo apps (demos.html) --------------------------------------------
#
# The apps address recorded calls by index, and tools/build_site.py
# resolves those indices from DEMO_CALLS. These check the resolution is
# real, so a demo cannot ship pointing at a call that moved.

def test_every_demo_app_step_points_at_a_real_recorded_call(core, demo):
    apps = core.get("demo_apps")
    assert apps, f"core.json carries no demo_apps block; {REGEN}"
    calls = demo["calls"]
    refs = []
    for site in apps["screen"]:
        refs += [(f"screen/{site['label']}/{s['label']}", s["tool"], s["call"])
                 for s in site["steps"]]
    refs += [(f"meetings/{v['label']}", "civic.search_meetings", v["call"])
             for v in apps["meetings"]]
    refs += [(f"code/{s['crumb']}", s["tool"], s["call"])
             for s in apps["code"]]
    assert refs, "no demo app declares a step"
    for where, tool, index in refs:
        assert 0 <= index < len(calls), (
            f"{where} points at trail position {index}, and the trail has "
            f"{len(calls)} calls; {REGEN}")
        actual = (calls[index].get("audit") or {}).get("tool")
        assert actual == tool, (
            f"{where} expects {tool} at trail position {index} and the "
            f"trail has {actual} there — the demo would show the wrong "
            f"answer with a straight face; {REGEN}")


def test_the_demo_apps_resolve_from_the_builder():
    """The indices are computed, not typed. Calling the builder proves a
    reference that no longer resolves fails the BUILD rather than
    rendering as an empty panel on the published page."""
    import sys

    sys.path.insert(0, str(ROOT / "tools"))
    import build_site

    apps = build_site.demo_apps()
    assert set(apps) == {"screen", "meetings", "code"}
    assert all(apps.values()), "a demo app resolved to no steps"


def test_the_meetings_demo_shows_a_gap_beside_an_empty(core, demo):
    """The pair the meetings app exists for. A registry gap and a covered
    locality with nothing in the window must both be on the page, because
    the demo's whole point is that they do not look the same."""
    calls = demo["calls"]
    shapes = {}
    for view in core["demo_apps"]["meetings"]:
        cov = (calls[view["call"]].get("envelope") or {}).get("coverage") or {}
        shapes[view["label"]] = (cov.get("registry"), cov.get("result"))
    assert ("none", "empty") in shapes.values(), (
        "the meetings demo shows no registry gap; the panel that proves "
        "a gap is not an empty calendar is missing")
    assert ("covered", "empty") in shapes.values(), (
        "the meetings demo shows no clean empty to compare the gap with")
    assert ("covered", "hit") in shapes.values(), (
        "the meetings demo shows no meetings at all")


def test_the_code_demo_walks_a_connected_path(core, demo):
    """Each step of the Code walk has to be reachable from the one above
    it, or the app is four unrelated calls wearing breadcrumbs."""
    steps = core["demo_apps"]["code"]
    calls = demo["calls"]
    for parent, child in zip(steps, steps[1:]):
        block = ((calls[parent["call"]].get("envelope") or {})
                 .get("data") or {}).get("results", [{}])[0]
        rows = block.get("records") or []
        wanted = child["chapter"] or child["title"] or child["citation"]
        assert any(r.get("number") == wanted for r in rows), (
            f"the Code demo steps from {parent['crumb']!r} to "
            f"{child['crumb']!r}, and {wanted!r} is not among what "
            f"{parent['crumb']!r} returned")


NUMBER_WORDS = {"nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
                "thirteen": 13, "fourteen": 14, "fifteen": 15,
                "sixteen": 16, "seventeen": 17, "eighteen": 18,
                "nineteen": 19, "twenty": 20}


def test_llms_txt_states_the_tool_counts_the_profiles_actually_expose():
    """`docs/llms.txt` is hand-written, spells its counts as words, and is
    what an assistant reads instead of the page. It said fifteen tools
    and nine in `default` for as long as that was true and would have
    gone on saying it — this is the floor under the sentence."""
    import re

    from commonwealth.core.toolreg import expand_profile
    from commonwealth.servers.build import registries

    text = (ROOT / "docs" / "llms.txt").read_text()
    match = re.search(
        r"(\w+) tools, (\w+) of them in the default set and (\w+) in "
        r"discovery", text)
    assert match, ("docs/llms.txt no longer states its tool counts in the "
                   "sentence this test reads; update both together")
    regs = registries()
    claimed = [NUMBER_WORDS.get(w.lower()) for w in match.groups()]
    actual = [len(expand_profile(p, regs))
              for p in ("all", "default", "discovery")]
    assert claimed == actual, (
        f"docs/llms.txt claims {match.group(0)!r}, and the profiles expose "
        f"{actual[0]} tools with {actual[1]} in default and {actual[2]} in "
        "discovery")


def test_the_coverage_demo_has_a_real_ambiguity_to_handle(site):
    """The demo used to resolve a typed prefix by taking the first match,
    and this is what that cost (found in review of PR #56).

    "Fairfax" is a prefix of two governments, and they do NOT have the
    same coverage — the county has a registered zoning source and the
    city does not. Picking the alphabetically first told a reader that
    Fairfax zoning was uncovered, which is wrong for the county and is
    the single confusion this project exists to prevent.

    Pinned as data rather than as JS behaviour: if the table or the
    registry ever changes so the two agree, the demo's ambiguity path
    stops being exercised by anything real and this says so.
    """
    by_name = {j["name"]: j["id"] for j in site["jurisdictions"]}
    prefixed = sorted(i for n, i in by_name.items()
                      if n.lower().startswith("fairfax"))
    assert prefixed == ["va:fairfax-city", "va:fairfax-county"], (
        "'Fairfax' no longer names exactly two governments")

    differing = []
    for capability, cov in site["capability_coverage"].items():
        covered = {c["jurisdiction"] for c in cov.get("covered", [])}
        if ("va:fairfax-county" in covered) != ("va:fairfax-city" in covered):
            differing.append(capability)
    assert differing, (
        "the two Fairfaxes now have identical coverage for every "
        "capability, so nothing on the site demonstrates why a shared "
        "name may not be resolved by picking one")


def test_no_page_hardcodes_the_size_of_the_recorded_trail(demo):
    """index.html linked to "All 39 recorded calls" while the trail held
    forty-five (found 2026-09-10). The count is derived now; this stops
    the next one being typed.

    Any number that is not the current call count is caught, so this
    fails whether the number goes stale or a new one is typed in.
    """
    import re

    pattern = re.compile(r"(\d+)\s+recorded\s+calls?", re.I)
    actual = demo["call_count"]
    for page in PAGES:
        for found in pattern.findall((DOCS / page).read_text()):
            assert int(found) == actual, (
                f"{page} says {found!r} recorded calls and the trail holds "
                f"{actual}. Derive it from demo_meta.call_count rather than "
                "typing it; see renderCallsLink in site.js")


def test_the_landing_page_points_at_the_demos(core):
    """A page nothing links to is a page nobody opens. The nav carries it
    on every page; this is the one in the body, beside the trail it is an
    alternative reading of."""
    body = (DOCS / "index.html").read_text()
    main = body[body.index("<main"):body.index("</main>")]
    assert 'href="demos.html"' in main, (
        "index.html's nav links the demos and its body does not")


def test_committed_demo_staleness_matches_what_a_build_would_produce(demo):
    """The site data is generated and committed, and `stale_source` is
    measured against wall-clock now (GitHub issue #57). So a recording
    that is fresh today warns in a year, and the committed JSON silently
    stops matching what `build_site.py` produces.

    This is the legible version of that failure. It says which fixtures
    crossed the line and what to do, instead of leaving a diff in a
    440 KB JSON file for someone to interpret.
    """
    from commonwealth.core.assemble import _age_seconds
    from commonwealth.core.registry import SourceRegistry
    from commonwealth.runtime import SOURCES_DIR

    registry = SourceRegistry.load(SOURCES_DIR)
    drifted = []
    for call in demo["calls"]:
        envelope = call.get("envelope") or {}
        warned = {w["code"] for w in envelope.get("warnings", [])}
        for source in envelope.get("provenance", []):
            manifest = registry.get(source["source_id"])
            if manifest is None or not source.get("source_updated_at"):
                continue
            limit = manifest.freshness.stale_after_seconds()
            if limit is None:
                continue
            age = _age_seconds(source["source_updated_at"],
                               source["retrieved_at"])
            if age is None:
                continue
            # What a build today would decide, against what is committed.
            if (age > limit) != ("stale_source" in warned):
                drifted.append(
                    f"{source['source_id']} (vintage "
                    f"{source['source_updated_at']}, cadence "
                    f"{manifest.freshness.expected_cadence})")
    assert not drifted, (
        "these recordings have aged across their source's declared "
        f"cadence since the site data was generated: {sorted(set(drifted))}. "
        "The committed docs/data/*.json no longer matches what "
        f"build_site.py produces. {REGEN} — and consider re-recording the "
        "fixtures themselves with `commonwealth sources sample`, since "
        "the underlying government data has moved on too.")


# --- SEO: what a crawler and a link preview read ---------------------------
#
# Hand-written in each page's head, so each is a place to drift. These
# are the floor under the ones that matter.

SITE = "https://pranava0x0.github.io/Commonwealth-MCP/"


def _head(page: str) -> str:
    html = (DOCS / page).read_text()
    return html[:html.index("</head>")]


def _meta(html: str, attr: str, name: str) -> str | None:
    m = re.search(rf'<meta {attr}="{re.escape(name)}" content="([^"]*)"', html)
    return m.group(1) if m else None


@pytest.mark.parametrize("page", PAGES)
def test_each_page_has_exactly_one_h1(page):
    """The reference pages had none: their title was an h2, so a crawler
    and a screen reader found no page heading at all."""
    assert (DOCS / page).read_text().count("<h1") == 1, page


@pytest.mark.parametrize("page", PAGES)
def test_each_page_names_itself_canonically(page):
    want = SITE if page == "index.html" else SITE + page
    head = _head(page)
    assert f'<link rel="canonical" href="{want}">' in head, page
    assert _meta(head, "property", "og:url") == want, page


@pytest.mark.parametrize("page", PAGES)
def test_titles_and_descriptions_fit_what_a_results_page_shows(page):
    """Search results cut a description at about 160 characters and a
    title at about 60-70, so what fits is what gets read."""
    head = _head(page)
    title = re.search(r"<title>([^<]*)</title>", head).group(1)
    desc = _meta(head, "name", "description")
    assert 10 <= len(title) <= 70, (page, len(title), title)
    assert desc and 50 <= len(desc) <= 160, (page, len(desc or ""), desc)
    assert "Commonwealth-MCP" in title, page


@pytest.mark.parametrize("page", PAGES)
def test_each_page_carries_a_complete_link_preview(page):
    head = _head(page)
    for attr, name in (("property", "og:title"), ("property", "og:description"),
                       ("property", "og:type"), ("property", "og:image"),
                       ("property", "og:site_name"), ("name", "twitter:card"),
                       ("name", "twitter:image")):
        assert _meta(head, attr, name), f"{page} has no {name}"
    image = _meta(head, "property", "og:image")
    assert image.startswith(SITE), "a preview image must be an absolute URL"
    local = DOCS / image[len(SITE):]
    assert local.exists(), f"{page} points og:image at {local}, which is missing"
    assert local.stat().st_size < 200_000, "link-preview image over 200 KB"


@pytest.mark.parametrize("page", PAGES)
def test_each_page_embeds_structured_data_that_parses(page):
    html = (DOCS / page).read_text()
    m = re.search(r'<script type="application/ld\+json" id="data-jsonld">'
                  r'(.*?)</script>', html, re.S)
    assert m, f"{page} has no JSON-LD block"
    data = json.loads(m.group(1))
    assert data.get("@context") == "https://schema.org", page
    assert data.get("@graph"), f"{page}'s JSON-LD is empty; {REGEN}"


def test_the_sitemap_lists_every_page_and_robots_points_at_it():
    """Both are generated from PAGES, so a new page is in the sitemap
    without anyone remembering it."""
    sitemap = (DOCS / "sitemap.xml").read_text()
    locs = re.findall(r"<loc>([^<]+)</loc>", sitemap)
    want = [SITE if p == "index.html" else SITE + p for p in PAGES]
    assert locs == want, f"sitemap drifted from PAGES; {REGEN}"
    robots = (DOCS / "robots.txt").read_text()
    assert f"Sitemap: {SITE}sitemap.xml" in robots


def test_the_featured_heading_counts_the_steps_it_shows(core):
    """The landing page said "One walk, four answers" as a literal; the
    script now sets it from the step count, and the static fallback a
    reader without JavaScript sees has to agree."""
    words = ["zero", "one", "two", "three", "four", "five", "six",
             "seven", "eight", "nine", "ten"]
    n = len(core["featured"]["steps"])
    html = (DOCS / "index.html").read_text()
    m = re.search(r'id="featured-title">One walk, (\w+) answers<', html)
    assert m and m.group(1) == words[n], (
        f"the featured heading says {m and m.group(1)!r}; the walk has {n}")


def test_the_fixtures_build_reaches_no_network(monkeypatch, demo):
    """`build_site.py --fixtures` is the offline build, and it was not:
    the agenda-platform adapter was never given the replay fetcher, so
    the meetings calls in the committed trail were answered by a live
    request to the publisher, and the page showed no outbound request
    for them. With the network refused they failed as EgressRefused and
    the Demos page had no meetings at all (found regenerating the site
    for review round 3 of PR #56).

    So the trail is rebuilt here with the network refused, and what it
    produces has to agree with what is committed on every call's
    coverage. A call that only answers when the network is on cannot
    get in.
    """
    import asyncio
    import sys

    sys.path.insert(0, str(ROOT / "tools"))
    import build_site

    monkeypatch.setenv("COMMONWEALTH_DENY_NETWORK", "1")
    fresh = asyncio.run(build_site.run_demo("fixtures"))

    def shape(call):
        audit = call["audit"]
        envelope = call.get("envelope") or {}
        coverage = envelope.get("coverage") or {}
        return (audit["tool"], json.dumps(audit["args"], sort_keys=True),
                coverage.get("registry"), coverage.get("execution"),
                coverage.get("result"), len(envelope.get("evidence", [])),
                call["is_error"],
                [f["error"] for f in coverage.get("source_failures", [])])

    refused = [s for s in map(shape, fresh["calls"]) if "EgressRefused" in s[-1]]
    assert refused == [], (
        "these calls in the fixtures build reached for the network, so an "
        f"adapter is missing its replay fetcher: {refused}")
    assert list(map(shape, fresh["calls"])) == list(map(shape, demo["calls"])), (
        f"the committed trail is not what an offline build produces; {REGEN}")
