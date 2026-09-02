"""Every skill: the format rules, and each walk replayed over fixtures.

`design/skills.md` § 5 asks every skill for bench tasks, and #28 builds the
runner that scores them with a model in the loop. This file is the half
that needs no model: the format checks are derived from what is on disk,
so they cover a skill written after this file was, and each walk is
executed against recorded government responses for the cases its own tasks
describe. A walk that cannot be executed is prose, whatever its evals say.

Every expectation is read out of `evals/skills/<name>/*.yaml` rather than
typed twice, so a task and this file cannot drift apart.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from commonwealth.core.errors import SourceUnavailable
from commonwealth.core.registry import SourceRegistry
from commonwealth.core.skills import load_skills
from commonwealth.domains.geo import (find_buildings, find_environmental_sites,
                                      find_parcel, find_roads, find_zoning,
                                      resolve_location)
from commonwealth.domains.registry import resolve_jurisdiction
from commonwealth.runtime import PROJECT_ROOT, SOURCES_DIR
from commonwealth.servers.build import registries
from tests.conftest import ReplayFetcher, build_ctx, load_all_recordings

SKILLS_DIR = PROJECT_ROOT / "skills"
TASKS_DIR = PROJECT_ROOT / "evals" / "skills"

SKILL_NAMES = sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))


@pytest.fixture
def ctx():
    return build_ctx()


def _frontmatter(name: str) -> dict:
    text = (SKILLS_DIR / name / "SKILL.md").read_text()
    assert text.startswith("---\n"), f"{name}: SKILL.md has no frontmatter"
    return yaml.safe_load(text.split("---\n", 2)[1])


def _body(name: str) -> str:
    return (SKILLS_DIR / name / "SKILL.md").read_text().split("---\n", 2)[2]


def _tasks(name: str) -> list[dict]:
    return [yaml.safe_load(p.read_text())
            for p in sorted((TASKS_DIR / name).glob("*.yaml"))]


def _task(skill: str, stem: str) -> dict:
    return yaml.safe_load((TASKS_DIR / skill / f"{stem}.yaml").read_text())


# --- format, over every skill on disk (skills.md § 1) ----------------------

def test_there_is_at_least_one_skill():
    """The checks below are parametrized over what is on disk, so an empty
    skills directory would pass all of them without running anything."""
    assert SKILL_NAMES, "no skills found; every check below is vacuous"


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_the_skill_carries_the_fields_the_format_requires(name):
    fm = _frontmatter(name)
    assert fm["name"] == name, "name must match the directory"
    assert len(fm["name"]) <= 64
    assert fm["description"].strip(), "the router reads the description"
    assert len(fm["description"]) < 1024, "description is metadata, not prose"
    assert "compatibility" in fm, (
        "a host missing the servers should be able to say so")


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_the_declared_capabilities_are_real(name):
    """skills.md § 1: `commonwealth.required_capabilities` is the
    machine-readable half, and a capability outside the vocabulary cannot
    be routed to anything."""
    declared = _frontmatter(name)["metadata"]["commonwealth"]
    vocab = set(SourceRegistry.load(SOURCES_DIR).capability_vocab)
    required = declared["required_capabilities"]
    assert required, "a skill with no required capabilities declares nothing"
    unknown = [c for c in required + declared.get("optional_capabilities", [])
               if c not in vocab]
    assert unknown == [], (
        f"{name} declares capabilities absent from "
        f"sources/capabilities.yaml: {unknown}")


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_the_walk_names_capabilities_and_never_a_tool(name):
    """skills.md § 3's standing rule: a walk names `zoning.lookup`, never
    `geo.find_zoning`, so a skill survives a tool rename. Checked against
    the live registry rather than a typed list of tool names."""
    tool_names = {spec.name for reg in registries().values()
                  for spec in reg.tools("*")}
    assert tool_names, "the tool registry is empty; the check basis broke"
    named = sorted(n for n in tool_names if n in _body(name))
    assert named == [], f"{name} names tools in its body: {named}"


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_the_body_stays_under_the_length_the_spec_sets(name):
    assert len(_body(name).splitlines()) < 500, "skills.md § 1: under 500"


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_every_skill_ships_its_bench_tasks(name):
    """skills.md § 5: three or more tasks that exercise the whole walk,
    each naming fixtures that exist. "A skill without evals is a blog post
    in a trench coat."""
    tasks = _tasks(name)
    assert len(tasks) >= 3, f"{name} has {len(tasks)} tasks; § 5 asks for 3+"
    for task in tasks:
        assert task["skill"] == name, task["id"]
        assert task["fixtures"], f"{task['id']} names no fixture"
        for fixture in task["fixtures"]:
            path = PROJECT_ROOT / "tests" / "fixtures" / "sources" / fixture
            assert path.is_dir(), f"{task['id']} names missing {fixture}"


def test_the_trap_kinds_are_covered_across_the_skill_set():
    """Per skills.md § 5 each skill wants an ambiguity trap, a no-coverage
    jurisdiction, and an outage. Not every walk can produce all three —
    `whose-government` answers from a statewide source that is always
    registered — so the requirement is checked over the set rather than
    per skill, and each skill still has to carry at least one trap."""
    by_skill = {name: {t for task in _tasks(name)
                       for t in (task.get("traps") or [])}
                for name in SKILL_NAMES}
    everything = set().union(*by_skill.values())
    assert {"ambiguity", "registry_gap", "outage"} <= everything, everything
    thin = [n for n, traps in by_skill.items() if not traps]
    assert thin == [], f"{thin} carry no trap task at all"


def test_no_two_skills_claim_the_same_name():
    assert len(SKILL_NAMES) == len(set(SKILL_NAMES))


# --- parcel-zoning-screen, replayed (issue #27's four cases) --------------

async def test_one_polygon_parcel_returns_one_district(ctx):
    task = _task("parcel-zoning-screen", "one-polygon-parcel")
    pin = "0102 14  0231"
    assert pin in task["question"], "the task and the replay disagree on PIN"

    parcel = await find_parcel(ctx, jurisdiction="Fairfax County", pin=pin)
    assert parcel.coverage.result.value == "hit"

    env = await find_zoning(ctx, jurisdiction="Fairfax County", pin=pin)
    block = env.data["results"][0]
    assert block["parcel_polygons_intersected"] == 1
    districts = [r["district"] for r in block["records"]]
    assert districts == task["expected"]["districts"], districts
    assert env.coverage.registry.value == "covered"
    assert env.coverage.result.value == "hit"

    # Output-contract § 4.4: the caveat is structural, so it is in the
    # envelope whether or not the model remembers to say it.
    assert "screening_only" in {w.code for w in env.warnings}


async def test_a_split_parcel_reports_every_polygons_district(ctx):
    """The multi-polygon PIN from #17. The skill's step 2 says to report
    the union and call the parcel split; this asserts the walk has the
    facts to do that — how many polygons, and which districts."""
    task = _task("parcel-zoning-screen", "split-parcel-two-polygons")
    env = await find_zoning(ctx, jurisdiction="Richmond City",
                            pin="E0000720034")
    block = env.data["results"][0]
    assert (block["parcel_polygons_intersected"]
            == task["expected"]["parcel_polygons_intersected"])
    assert env.data["parcel_note"], (
        "nothing tells the caller the parcel is split rather than the "
        "sources disagreeing")
    assert "split" in env.data["parcel_note"]
    for row in block["records"]:
        assert row["evidence_refs"], row


async def test_a_locality_with_no_zoning_source_reads_as_not_covered(ctx):
    """Charles City County publishes parcels and no zoning. The parcel
    step succeeds and the zoning step is a registry gap, and those are
    different facts in the same answer."""
    parcel = await find_parcel(ctx, jurisdiction="Charles City County",
                               pin="7-4-B-2")
    assert parcel.coverage.registry.value == "covered"
    assert parcel.coverage.result.value == "hit"

    env = await find_zoning(ctx, jurisdiction="Charles City County",
                            pin="7-4-B-2")
    assert env.coverage.registry.value == "none", (
        "a missing source must not read as a checked-and-empty layer")
    assert env.coverage.result.value == "empty"
    reasons = {g.reason for g in env.coverage.jurisdictions_unavailable}
    assert "no_registered_source" in reasons


async def test_a_locality_with_no_registered_source_at_all(ctx):
    """Craig County has neither. The zoning answer is the same shape as
    Charles City's, which is why the skill's walk distinguishes them at
    step 1 rather than step 2."""
    env = await find_zoning(ctx, jurisdiction="Craig County", pin="anything")
    assert env.coverage.registry.value == "none"
    assert env.coverage.result.value == "empty"
    assert env.data["results"] == []
    gaps = {g.jurisdiction for g in env.coverage.jurisdictions_unavailable}
    assert "va:craig-county" in gaps


# --- the two traps a model is in the loop for, pinned at the tool layer ----

async def test_the_ambiguity_trap_returns_candidates_and_chooses_nothing(
        ctx):
    """The skill's step 1 says to stop and show candidates. The envelope
    has to give it something to show."""
    task = _task("parcel-zoning-screen", "ambiguous-fairfax")
    env = await resolve_jurisdiction(ctx, query="Fairfax")
    assert env.requires_user_choice is True
    assert env.data["resolved"] is None, "the envelope picked one"
    ids = {c["id"] for c in env.data["candidates"]}
    assert set(task["expected"]["candidates"]) <= ids, ids


async def test_the_outage_trap_is_a_failure_not_an_empty_answer(ctx):
    """A zoning layer answering 503 mid-walk. The skill's escalation table
    sends this to "report what was read and name the source that failed",
    which needs the failure in the envelope rather than a short result."""
    task = _task("parcel-zoning-screen", "source-outage-mid-walk")

    class _Outage:
        def __init__(self) -> None:
            self.replay = ReplayFetcher(load_all_recordings())

        async def fetch_json(self, url: str, params: dict) -> dict:
            if "fairfaxcounty.gov" in url:
                raise SourceUnavailable("simulated outage (HTTP 503)")
            return await self.replay.fetch_json(url, params)

    env = await find_zoning(build_ctx(fetcher=_Outage()),
                            jurisdiction="Fairfax County",
                            pin="0102 14  0231")
    expected = task["expected"]["coverage"]
    assert env.coverage.execution.value == expected["execution"]
    assert env.coverage.result.value == expected["result"]
    assert env.coverage.registry.value == expected["registry"], (
        "an outage must never read as a registry gap")
    assert [f.source_id for f in env.coverage.source_failures] == [
        "va-fairfax-parcels-zoning"]


# --- whose-government, replayed -------------------------------------------

async def test_an_ambiguous_name_returns_both_and_picks_neither(ctx):
    """The trap the walk exists for. Two governments share the name and
    the input cannot distinguish them, so there is no answer to give."""
    task = _task("whose-government", "ambiguous-name")
    env = await resolve_jurisdiction(ctx, query="Fairfax")
    assert env.requires_user_choice is True
    assert env.data["resolved"] is None, "the envelope picked one"
    ids = {c["id"] for c in env.data["candidates"]}
    assert set(task["expected"]["candidates"]) <= ids, ids
    for candidate in env.data["candidates"]:
        assert candidate["distinguisher"], (
            "a candidate with no distinguisher cannot be chosen between")


async def test_a_postal_city_is_reported_as_a_postal_city(ctx):
    """Mail addressed to Alexandria that is governed by Fairfax County.
    The wrong answer here is the plausible one."""
    env = await resolve_location(
        ctx, address="6800 Beulah St, Alexandria, VA 22310")
    assert env.data["resolved"]["id"] == "va:fairfax-county"
    assert env.data["geocode"]["postal_city"] == "ALEXANDRIA"
    assert env.data.get("postal_city_note"), (
        "nothing tells the caller the envelope city is not the government")


async def test_a_town_address_returns_the_town_and_its_county(ctx):
    task = _task("whose-government", "town-and-county-both")
    env = await resolve_location(ctx,
                                 address="127 Center St S, Vienna, VA 22180")
    assert env.data["resolved"]["id"] == task["expected"]["jurisdiction"]
    layered = {a["id"] for a in env.data["layered_authorities"]}
    assert set(task["expected"]["layered"]) <= layered, layered


async def test_a_zip_returns_every_locality_it_touches(ctx):
    """A ZIP is a mail delivery route. One answer for a ZIP crossing three
    localities is a guess wearing a fact's clothes."""
    task = _task("whose-government", "zip-spanning-localities")
    env = await resolve_location(ctx, zip_code="24450")
    ids = {loc["id"] for loc in env.data["localities_touched"]}
    assert ids == set(task["expected"]["localities"]), ids


async def test_a_surrendered_charter_resolves_to_what_it_became(ctx):
    """Someone saying "Bedford City" is usually reading an old document,
    which is a fact the answer should carry."""
    task = _task("whose-government", "a-city-that-became-a-town")
    env = await resolve_jurisdiction(ctx, query="Bedford City")
    assert env.data["resolved"]["id"] == task["expected"]["jurisdiction"]
    assert env.data["resolved"]["basis"] == task["expected"]["basis"]
    layered = {a["id"] for a in env.data["layered_authorities"]}
    assert "va:bedford-county" in layered, (
        "the county that now governs the ground is missing")


# --- site-context-screen, replayed ----------------------------------------

async def test_a_truncated_building_answer_keeps_what_it_retrieved(ctx):
    """The result-store case (#33). The walk tells the caller to read the
    handle rather than the short list, so the handle has to be there."""
    task = _task("site-context-screen", "dense-query-truncates")
    env = await find_buildings(ctx, jurisdiction="Richmond City",
                               lon=-77.4360, lat=37.5407,
                               radius_meters=800.0)
    block = env.data["results"][0]
    assert len(block["records"]) == task["expected"]["inline_records"]
    assert block["record_count"] > task["expected"]["record_count_over"]
    assert block["full_records_ref"], "the retrieved records were dropped"
    stored = ctx.results.get(block["full_records_ref"])
    assert len(stored.payload["records"]) == block["record_count"]


async def test_no_monitoring_station_is_never_an_all_clear(ctx):
    """The most consequential empty answer in the toolset."""
    env = await find_environmental_sites(ctx, jurisdiction="Virginia",
                                         lon=-74.5, lat=36.5)
    assert env.coverage.result.value == "empty"
    assert env.coverage.registry.value == "covered", (
        "the source answered; this is a real empty, not a gap")
    # Asserted as what the envelope must say, not as words it must avoid.
    # The warning legitimately contains "safe" — in "NOT a determination
    # that any site is safe" — so scanning for the word would fail on the
    # disclaimer that makes the answer correct. What the model then does
    # with this is the task file's `must_not_say`, which #28's scorer
    # checks against a model's output rather than against an envelope.
    prose = " ".join(w.message for w in env.warnings).lower()
    assert "not a complete inventory" in prose, (
        "an empty environmental answer that does not say the layer is no "
        "inventory reads as an all-clear")
    assert "not a determination" in prose, (
        "the answer does not disclaim being a judgement about the site")


async def test_two_road_sources_come_back_unreconciled(ctx):
    """VDOT models routes and VGIN aggregates local centerlines. Both
    answer, neither is ranked, and the disagreement is the finding."""
    task = _task("site-context-screen", "two-road-sources-disagree")
    env = await find_roads(ctx, jurisdiction="Vienna",
                           lon=-77.2653, lat=38.9012)
    sources = [b["source_id"] for b in env.data["results"]]
    assert len(sources) == task["expected"]["sources_returned"], sources
    assert "va-vdot-lrs-routes" in sources
    assert "va-vgin-road-centerlines" in sources


async def test_a_locality_with_no_source_reads_as_not_covered(ctx):
    """Same shape the parcel walk reports, one capability over, and it
    carries the escalation hint a skill can act on."""
    env = await find_zoning(ctx, jurisdiction="Craig County", pin="1")
    assert env.coverage.registry.value == "none"
    assert [a.suggested_capability for a in env.next_actions] == [
        _task("site-context-screen",
              "no-source-for-this-locality")["expected"]["next_action"]]


# --- the startup capability check (design/hub-catalog.md § 2) --------------

def test_no_shipped_skill_needs_a_capability_this_registry_cannot_serve():
    """The state worth pinning: every skill on disk can complete its walk
    against what is registered today."""
    from commonwealth.servers.build import check_skill_capabilities

    assert check_skill_capabilities(build_ctx()) == []


def _one_impossible_skill(monkeypatch, *, required: bool):
    from commonwealth.core import skills as skills_mod
    from commonwealth.servers import build as build_mod

    real = skills_mod.load_skills

    def bent(path):
        found = real(path)
        assert found, "no skills on disk; the mutation has nothing to bend"
        first = found[0]
        extra = ("permit.lookup",)
        return [skills_mod.SkillRequirements(
            name=first.name, path=first.path,
            required_capabilities=first.required_capabilities
            + (extra if required else ()),
            optional_capabilities=first.optional_capabilities
            + (() if required else extra))]

    monkeypatch.setattr(build_mod, "load_skills", bent)
    return build_mod


def test_an_unroutable_capability_warns_and_the_server_still_starts(
        monkeypatch, caplog):
    """Mutation-checked, and it pins the warn-rather-than-refuse call.

    A fork registering one county's parcels has a working server and one
    skill that cannot finish its walk. Refusing to serve the tools that do
    work is the worse outcome — the same reasoning decision 0002's
    amendment applied to the profile floor.
    """
    import logging

    build_mod = _one_impossible_skill(monkeypatch, required=True)
    with caplog.at_level(logging.WARNING, logger="commonwealth.servers"):
        server = build_mod.build_server(build_ctx())
    assert server is not None, "the server must still start"
    assert "permit.lookup" in caplog.text
    assert any(name in caplog.text for name in SKILL_NAMES), caplog.text


def test_an_optional_capability_never_warns(monkeypatch, caplog):
    """An optional capability says the walk is better where it exists,
    which is a coverage statement rather than a prerequisite."""
    import logging

    build_mod = _one_impossible_skill(monkeypatch, required=False)
    with caplog.at_level(logging.WARNING, logger="commonwealth.servers"):
        build_mod.build_server(build_ctx())
    assert "permit.lookup" not in caplog.text


def test_a_checkout_with_no_skills_still_starts(tmp_path):
    """The normal state of this repository until 2026-09-01, and of any
    fork that removes the directory."""
    assert load_skills(tmp_path / "nothing-here") == []
