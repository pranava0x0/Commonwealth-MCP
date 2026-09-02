"""The docs site's baked data stays derived: committed JSON must match what
the live registries produce, and every demo envelope must validate against
the committed wire schema (generated output commits with its source)."""
import json
import re
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "data" / "site.json"
DEMO = ROOT / "docs" / "data" / "audit-demo.json"
RESOLVER = ROOT / "docs" / "data" / "resolver-demo.json"
REGEN = "regenerate: .venv/bin/python tools/build_site.py --fixtures"


@pytest.fixture(scope="module")
def site() -> dict:
    assert SITE.exists(), f"missing {SITE}; {REGEN}"
    return json.loads(SITE.read_text())


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
    print(f"site.json counts verified against live registries: "
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


def test_page_embeds_data_matching_the_committed_json(site, demo,
                                                       resolver_demo):
    """The page must work opened as a raw file (drag into a browser, email
    attachment) — fetch() rejects file:// URLs, so the data is embedded
    inline, not fetched. This locks the embedded copy against the committed
    docs/data/*.json so the two can't silently diverge."""
    html = (ROOT / "docs" / "index.html").read_text()
    assert "fetch(" not in html, \
        "the page must not fetch its data — embed it so file:// works"
    for block_id, expected in [("data-site", site), ("data-audit-demo", demo),
                               ("data-resolver-demo", resolver_demo)]:
        m = re.search(
            rf'<script type="application/json" id="{block_id}">(.*?)</script>',
            html, re.DOTALL)
        assert m, f"missing embedded data block #{block_id}"
        assert json.loads(m.group(1)) == expected, (
            f"embedded #{block_id} does not match docs/data/ — {REGEN}")
    assert "hand-typed" not in html  # the page renders, it never restates


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

READER_FACING = ("README.md", "docs/llms.txt", "docs/index.html")


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
    missing = [sk.name for sk in load_skills(ROOT / "skills")
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

    on_disk = {sk.name for sk in load_skills(ROOT / "skills")}
    listed = {sk["name"]: sk["status"] for sk in site["skills"]}
    for name in on_disk:
        assert listed.get(name) == "shipped", (
            f"{name} exists on disk and the page says {listed.get(name)!r}; "
            + REGEN)
    for name, status in listed.items():
        if name not in on_disk:
            assert status != "shipped", (
                f"the page calls {name} shipped and there is no "
                f"skills/{name}/SKILL.md")
