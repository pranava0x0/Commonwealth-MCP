"""Two towns with sources of their own, replayed.

Leesburg, in Loudoun County, publishes parcels and zoning; Loudoun
publishes nothing this project reads. Vienna, in Fairfax County, publishes
zoning alone; Fairfax publishes both. Between them they are the last slot
of the source-registry forcing set (design/source-registry.md § 6, GitHub
issue #10) and the two cases that slot existed for: a town and its county
both answering for one piece of ground, and a zoning source that has to
read its districts over another publisher's parcel polygon.

Every expected value is read from the fixture the sampler wrote, so a
re-record that changes what the town publishes changes the test with it.
"""
from __future__ import annotations

import json

import pytest

from commonwealth.core.errors import SourceUnavailable
from commonwealth.domains.geo import find_parcel, find_zoning
from commonwealth.runtime import PROJECT_ROOT
from tests.conftest import ReplayFetcher, build_ctx, load_all_recordings

FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "sources"
VIENNA = "va-vienna-town-zoning"
LEESBURG = "va-leesburg-town-parcels-zoning"
FAIRFAX = "va-fairfax-parcels-zoning"
VGIN = "va-vgin-statewide-parcels"
LOUDOUN = "va-loudoun-county-parcels-zoning"


def _summary(source_id: str) -> dict:
    return json.loads((FIXTURES / source_id / "recorded.json").read_text())[
        "summary"]


def _by_source(env) -> dict[str, dict]:
    return {blk["source_id"]: blk for blk in env.data["results"]}


class _HostOutage:
    """Fails every request to hosts matching any substring; replays the
    rest from the recordings."""

    def __init__(self, *fail_substrings: str) -> None:
        self.fail = fail_substrings
        self.replay = ReplayFetcher(load_all_recordings())

    async def fetch_json(self, url: str, params: dict) -> dict:
        if any(s in url for s in self.fail):
            raise SourceUnavailable("simulated outage (HTTP 503)")
        return await self.replay.fetch_json(url, params)


class _TruncatedParcelLayer:
    """Replays everything, but the Fairfax parcel layer reports that it
    capped its response and cannot page.

    Both halves are needed together: `exceededTransferLimit` alone would
    send the adapter after four more pages the recording does not have,
    and services that cap without supporting `resultOffset` are real.
    """

    PARCELS = "OpenData_A9/FeatureServer/0"

    def __init__(self) -> None:
        self.replay = ReplayFetcher(load_all_recordings())

    async def fetch_json(self, url: str, params: dict) -> dict:
        payload = await self.replay.fetch_json(url, params)
        if url.endswith(self.PARCELS + "/query") and "features" in payload:
            payload["exceededTransferLimit"] = True
        elif url.endswith(self.PARCELS):
            payload.setdefault("advancedQueryCapabilities", {})[
                "supportsPagination"] = False
        return payload


@pytest.fixture
def ctx():
    return build_ctx()


# --- Vienna: the town's districts and the county's, for one point -------

async def test_a_point_in_vienna_returns_the_town_and_the_county(ctx):
    s = _summary(VIENNA)
    lon, lat = s["sample_point"]
    env = await find_zoning(ctx, jurisdiction="Vienna", lon=lon, lat=lat)
    by = _by_source(env)
    assert set(by) == {VIENNA, FAIRFAX}, sorted(by)
    assert env.coverage.jurisdictions_searched == [
        "va:vienna-town", "va:fairfax-county", "va"]
    assert env.coverage.registry.value == "covered"
    assert env.coverage.result.value == "hit"
    assert by[VIENNA]["record_count"] == 1
    assert by[FAIRFAX]["record_count"] == 1
    assert [r["district"] for r in by[VIENNA]["records"]] == \
        s["point_districts"]
    assert env.data["comparison"]["agreement"] is True, (
        "both governments draw this ground the same; a disagreement here "
        "would be a finding, not an error")
    assert "screening_only" in {w.code for w in env.warnings}


async def test_a_vienna_parcel_number_reads_the_town_over_the_county_parcel(
        ctx):
    """The town publishes no parcel layer, so its districts are read over
    the county's polygon, and the evidence says so."""
    s = _summary(VIENNA)
    env = await find_zoning(ctx, jurisdiction="Vienna", pin=s["sample_pin"])
    by = _by_source(env)
    vienna = by[VIENNA]
    assert vienna["parcel_source_id"] == s["parcel_source"] == FAIRFAX
    assert vienna["parcel_polygons_intersected"] == s["parcel_polygons"] == 1
    assert [r["district"] for r in vienna["records"]] == s["pin_districts"]
    assert "parcel_source_id" not in by[FAIRFAX], (
        "the county read its own parcel layer and borrowed nothing")

    evidence = {e.id: e for e in env.evidence}
    provenance = {p.id: p for p in env.provenance}
    parcel_evidence = [evidence[ref] for ref in vienna["parcel_evidence_refs"]]
    assert {provenance[e.source_ref].source_id
            for e in parcel_evidence} == {FAIRFAX}
    district = vienna["records"][0]
    assert set(vienna["parcel_evidence_refs"]) <= set(district["evidence_refs"]), (
        "the district rests on the parcel polygon that produced it")
    zoning_evidence = [evidence[ref] for ref in district["evidence_refs"]
                       if ref not in vienna["parcel_evidence_refs"]]
    assert zoning_evidence, "the district carries no evidence of its own"
    for e in zoning_evidence:
        assert f"parcel_geometry_from:{FAIRFAX}" in e.transformations, (
            e.transformations)


async def test_a_parcel_number_no_source_has_leaves_the_town_layer_unqueried(
        ctx):
    env = await find_zoning(ctx, jurisdiction="Vienna", pin="NO SUCH PIN")
    by = _by_source(env)
    assert by[VIENNA]["record_count"] == 0
    assert "not queried" in by[VIENNA]["note"]
    assert "outage" not in by[VIENNA]["note"]
    assert by[FAIRFAX]["record_count"] == 0
    assert env.coverage.registry.value == "covered"
    assert env.coverage.execution.value == "complete"
    assert env.coverage.result.value == "empty"
    consulted = {p.source_id for p in env.provenance}
    assert {FAIRFAX, VGIN} <= consulted, (
        "every parcel source asked for the polygon belongs in provenance, "
        f"matched or not: {sorted(consulted)}")
    assert "comparison" not in env.data, (
        "a source that was never queried has no answer to compare")


async def test_a_miss_taken_while_another_parcel_source_is_down_says_so():
    """Fairfax answers and does not have the PIN; VGIN is down. Saying no
    parcel source has it states a fact about a source that was never
    read, and the note exists precisely because a miss and an outage are
    different answers."""
    ctx = build_ctx(fetcher=_HostOutage("vgin"))
    env = await find_zoning(ctx, jurisdiction="Vienna", pin="NO SUCH PIN")
    note = _by_source(env)[VIENNA]["note"]
    assert "not a definitive miss" in note, note
    assert VGIN in note, ("the note names the source that could not be "
                          f"reached: {note}")
    assert "no parcel source for this jurisdiction has PIN" not in note, note
    assert env.coverage.execution.value == "partial", (
        "a source failed, so the call was not complete")


def _town_sorted_first(ctx):
    """A copy of Vienna's manifest under an id that sorts before the
    county's, so selection hands the town to find_zoning first. Same
    service, so the recordings replay."""
    import yaml

    from commonwealth.core.registry import SourceManifest
    from commonwealth.runtime import SOURCES_DIR

    doc = yaml.safe_load((SOURCES_DIR / "local" / "vienna-town"
                          / "zoning.yaml").read_text())
    doc["id"] = "va-a-town-zoning"
    return SourceManifest.model_validate(doc)


async def test_the_order_sources_are_selected_in_does_not_change_the_answer():
    """Fairfax sorts before Vienna by id, so the county's own parcel
    query runs first and the town reuses it. A town whose id sorts first
    borrows first, and the county must then reuse the borrow rather than
    fetch and cite its parcel a second time."""
    s = _summary(VIENNA)
    ctx = build_ctx(extra_manifests=[_town_sorted_first(build_ctx())])
    env = await find_zoning(ctx, jurisdiction="Vienna", pin=s["sample_pin"])
    by = _by_source(env)
    assert list(by) == ["va-a-town-zoning", FAIRFAX], list(by)
    assert by["va-a-town-zoning"]["parcel_source_id"] == FAIRFAX
    fairfax_entries = [p for p in env.provenance if p.source_id == FAIRFAX]
    assert len(fairfax_entries) == 2, (
        "one parcel query and one zoning query, whichever government "
        f"asked first: {[(p.id, p.access_path) for p in fairfax_entries]}")
    assert [r["district"] for r in by[FAIRFAX]["records"]] == \
        [r["district"] for r in by["va-a-town-zoning"]["records"]]


async def test_a_town_sorted_first_still_reports_one_failure_per_source():
    s = _summary(VIENNA)
    ctx = build_ctx(extra_manifests=[_town_sorted_first(build_ctx())],
                    fetcher=_HostOutage("fairfaxcounty.gov", "vginmaps"))
    env = await find_zoning(ctx, jurisdiction="Vienna", pin=s["sample_pin"])
    failed = sorted(f.source_id for f in env.coverage.source_failures)
    assert failed == [FAIRFAX, VGIN], failed


async def test_no_parcel_source_at_all_is_neither_an_outage_nor_a_miss(ctx):
    """With every parcel source marked unavailable nothing is queried and
    nothing fails; the town's note has to say that rather than call it an
    outage or a missing parcel."""
    from commonwealth.core.registry import OperationalState

    for sid in (FAIRFAX, VGIN):
        ctx.sources.set_operational(sid, OperationalState.unavailable)
    env = await find_zoning(ctx, jurisdiction="Vienna", pin="0384 02  0143")
    by = _by_source(env)
    assert list(by) == [VIENNA], list(by)
    note = by[VIENNA]["note"]
    assert "registered or available" in note, note
    assert "outage" not in note
    assert env.coverage.source_failures == []
    assert env.coverage.execution.value == "complete"


async def test_the_town_layer_down_is_partial_with_the_county_answer():
    lon, lat = _summary(VIENNA)["sample_point"]
    ctx = build_ctx(fetcher=_HostOutage("OiQmCBznWDfkLRp1"))
    env = await find_zoning(ctx, jurisdiction="Vienna", lon=lon, lat=lat)
    assert env.coverage.execution.value == "partial"
    assert env.coverage.result.value == "hit", "the county's answer stands"
    assert [f.source_id for f in env.coverage.source_failures] == [VIENNA]
    assert [blk["source_id"] for blk in env.data["results"]] == [FAIRFAX]


async def test_every_parcel_source_down_is_an_outage_not_a_missing_parcel():
    """With no parcel source reachable there is no polygon to read the
    town's districts over. That is an outage, and the answer says so
    rather than reporting a parcel nobody has."""
    s = _summary(VIENNA)
    ctx = build_ctx(fetcher=_HostOutage("fairfaxcounty.gov", "vginmaps"))
    env = await find_zoning(ctx, jurisdiction="Vienna", pin=s["sample_pin"])
    by = _by_source(env)
    assert "outage" in by[VIENNA]["note"]
    assert FAIRFAX not in by, "the county's own path failed at its parcels"
    failed = [f.source_id for f in env.coverage.source_failures]
    assert sorted(failed) == [FAIRFAX, VGIN], (
        f"one entry per source, not one per attempt: {failed}")
    assert env.coverage.result.value == "empty"
    assert env.coverage.registry.value == "covered"
    assert env.coverage.execution.value == "failed", (
        "nothing was read; a block that says 'not queried' is not a "
        "partial answer")


async def test_a_parcel_source_that_is_down_is_asked_once_per_call():
    """The county's own path and the town's borrowed step both want the
    county's parcel. When that source is down, the second path reuses the
    remembered failure rather than spending another retry cycle on it."""
    s = _summary(VIENNA)
    outage = _HostOutage("fairfaxcounty.gov")
    calls: list[str] = []
    real = outage.fetch_json

    async def counting(url, params):
        if "fairfaxcounty.gov" in url and "/0/query" in url:
            calls.append(params.get("where", ""))
        return await real(url, params)

    outage.fetch_json = counting
    ctx = build_ctx(fetcher=outage)
    env = await find_zoning(ctx, jurisdiction="Vienna", pin=s["sample_pin"])
    assert len(calls) == 1, calls
    assert [f.source_id for f in env.coverage.source_failures] == [FAIRFAX]
    by = _by_source(env)
    assert by[VIENNA]["parcel_source_id"] == VGIN, (
        "with the county down the town's districts are read over VGIN's "
        "polygon")


# --- Leesburg: a town with its own parcels beside the statewide layer ---

async def test_a_leesburg_parcel_number_answers_from_the_town_and_the_county(
        ctx):
    """Two `primary` publishers now cover this ground — the town and its
    county — and selection queries the top two (decision 0005), so
    VGIN's statewide layer is no longer among them.

    That changed when Loudoun County was registered (2026-09-10). It is
    the intended behaviour rather than a regression: for a parcel inside
    Leesburg, the town and the county are closer authorities than a
    statewide aggregation of local submissions, and the rule is to take
    the top two rather than to take everything.
    """
    s = _summary(LEESBURG)
    env = await find_parcel(ctx, jurisdiction="Leesburg", pin=s["sample_pin"])
    by = _by_source(env)
    assert set(by) == {LEESBURG, LOUDOUN}, sorted(by)
    assert env.coverage.jurisdictions_searched == [
        "va:leesburg-town", "va:loudoun-county", "va"]
    town = by[LEESBURG]["records"]
    assert len(town) == 1
    assert town[0]["pin"] == s["sample_pin"]
    assert town[0]["address"]
    assert by[LOUDOUN]["record_count"] == 1, (
        "the town republishes the county's own parcel number (PA_MCPI), "
        "so one number reaches both layers")


async def test_a_leesburg_point_answers_from_both_parcel_sources(ctx):
    lon, lat = _summary(LEESBURG)["sample_point"]
    env = await find_parcel(ctx, jurisdiction="Leesburg", lon=lon, lat=lat)
    by = _by_source(env)
    assert set(by) == {LEESBURG, LOUDOUN}, sorted(by)
    for sid in (LEESBURG, LOUDOUN):
        assert by[sid]["record_count"] >= 1, sid


async def test_leesburg_zoning_by_parcel_number_reads_the_towns_own_map(ctx):
    s = _summary(LEESBURG)
    env = await find_zoning(ctx, jurisdiction="Leesburg", pin=s["sample_pin"])
    answered = [blk["source_id"] for blk in env.data["results"]]
    assert answered[0] == LEESBURG, (
        f"the town's own zoning map should lead; got {answered}")
    assert LOUDOUN in answered, (
        "the county publishes zoning too since 2026-09-10, and both "
        "governments' layers cover this ground")
    records = env.data["results"][0]["records"]
    assert [r["district"] for r in records] == s["zoning_districts"]
    assert records[0]["ordinance_link"].startswith(
        "https://www.leesburgva.gov/"), (
        "the link is the publisher's, returned as data")
    codes = {w.code for w in env.warnings}
    assert "screening_only" in codes
    # Freshness is per source, and two publishers answer this now. Both
    # town layers expose an edit date, so no freshness warning may name
    # the town; the county's MapServer exposes none, and the warning
    # that says so names the county rather than tarring both.
    town_entries = [p for p in env.provenance if p.source_id == LEESBURG]
    assert town_entries and all(p.source_updated_at for p in town_entries), [
        (p.source_id, p.source_updated_at) for p in env.provenance]
    assert not any(w.code == "freshness_unavailable" and w.source_id == LEESBURG
                   for w in env.warnings), (
        "the town publishes an edit date and was warned about anyway")
    # And it is said once per source, not once per layer.
    stale_notes = [w for w in env.warnings
                   if w.code == "freshness_unavailable"]
    assert len(stale_notes) == len({w.source_id for w in stale_notes})


async def test_loudoun_county_answers_from_its_own_source_not_the_towns(ctx):
    """Loudoun was this registry's standing example of a zoning gap until
    the county's own source was registered (2026-09-10). It is covered
    now — and the thing worth asserting is that it answers from the
    COUNTY's layer, never by borrowing the town's.

    The town's source is registered under the town. A county query that
    reached into it would be this project inventing jurisdiction that
    the Town of Leesburg holds and Loudoun County does not.
    """
    lon, lat = _summary(LEESBURG)["sterling_loudoun"]["point"]
    env = await find_zoning(ctx, jurisdiction="Loudoun County", lon=lon,
                            lat=lat)
    assert env.coverage.registry.value == "covered"
    answered = {b["source_id"] for b in env.data["results"]}
    assert answered == {"va-loudoun-county-parcels-zoning"}, (
        f"a Loudoun query answered from {answered}; the town's layer is "
        "the town's")


async def test_the_town_layer_down_leaves_leesburg_zoning_partial():
    """The town's host is down and the county's is not.

    Before Loudoun County was registered (2026-09-10) this was the whole
    answer failing, because the town was the only zoning publisher for
    this ground. Now a second government covers it, so the honest report
    is `partial` — one source answered, one did not, and the one that
    did not is named. The town's own map is still the authority for a
    parcel inside the town, so a partial answer here is a worse answer,
    and the failure list is what says so.
    """
    s = _summary(LEESBURG)
    ctx = build_ctx(fetcher=_HostOutage("7owdfh5mgjEgbCSM"))
    env = await find_zoning(ctx, jurisdiction="Leesburg", pin=s["sample_pin"])
    assert env.coverage.execution.value == "partial"
    assert env.coverage.registry.value == "covered", (
        "an outage is not a registry gap")
    assert [f.source_id for f in env.coverage.source_failures] == [LEESBURG]
    answered = {b["source_id"] for b in env.data["results"]}
    assert answered == {LOUDOUN}, (
        "the county's layer is on another host and should still answer")


async def test_a_truncated_borrowed_parcel_query_truncates_the_zoning_answer(
        ctx):
    """The parcel query bounds the zoning answer as much as the zoning
    query does. Vienna reads its districts over Fairfax's polygon, so a
    capped Fairfax parcel response leaves ground unintersected and
    districts on that ground unfound — reporting `complete` there would
    claim the whole parcel was considered."""
    s = _summary(VIENNA)
    truncating = build_ctx(fetcher=_TruncatedParcelLayer())
    env = await find_zoning(truncating, jurisdiction="Vienna",
                            pin=s["sample_pin"])
    assert env.coverage.pagination.value == "truncated"

    clean = await find_zoning(ctx, jurisdiction="Vienna",
                              pin=s["sample_pin"])
    assert clean.coverage.pagination.value == "complete", (
        "the same call over an untruncated parcel layer is complete, so "
        "the assertion above is about the cap and not about this PIN")
