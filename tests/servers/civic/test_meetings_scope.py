"""Two things a meetings answer says about its own reach: that a county's
calendar is not a town's, and that a long window is not all shown inline
(both found in review of PR #56).
"""
import dataclasses
import json
from pathlib import Path

from commonwealth.core.envelope import INLINE_RECORD_CAP
from commonwealth.core.results import MemoryResultStore
from commonwealth.domains.civic import search_meetings
from tests.conftest import build_ctx

BUSY = {"start_date": "2026-09-01", "end_date": "2026-09-30"}
RECORDING = (Path(__file__).resolve().parents[3] / "tests" / "fixtures"
             / "sources" / "va-richmond-city-meetings" / "recorded.json")


class EmptyFetcher:
    async def fetch_json_list(self, url, params):
        return []


class ManyFetcher:
    """`count` meetings in the platform's own shape, cloned from one
    recorded row so the parser sees exactly what it was written for."""

    def __init__(self, count: int) -> None:
        template = json.loads(RECORDING.read_text())["exchanges"][0]["response"][0]
        self.rows = []
        for i in range(count):
            row = dict(template)
            row["EventId"] = 900_000 + i
            row["EventDate"] = f"2026-09-{1 + i % 28:02d}T00:00:00"
            row["EventBodyName"] = f"Body {i}"
            self.rows.append(row)

    async def fetch_json_list(self, url, params):
        return self.rows


def _ctx(fetcher):
    # A memory store, so the test leaves nothing in the developer's cache.
    return dataclasses.replace(build_ctx(agenda_fetcher=fetcher),
                               results=MemoryResultStore(deterministic=True))


# --- whose calendar --------------------------------------------------------

async def test_a_towns_meetings_are_not_its_countys():
    """Scottsville sits in Albemarle County, which is on the agenda
    platform. The county's calendar is the county's; a town council is
    not on it, so the town is a gap beside a partial answer, never a
    covered locality."""
    env = await search_meetings(_ctx(EmptyFetcher()), "Scottsville", **BUSY)
    assert env.coverage.registry.value == "partial"
    assert [(g.jurisdiction, g.reason)
            for g in env.coverage.jurisdictions_unavailable] == [
        ("va:scottsville-town", "no_registered_source")]
    block = env.data["results"][0]
    assert block["source_id"] == "va-albemarle-county-meetings"
    assert "Scottsville" in block["scope_note"]
    assert "Albemarle County" in block["scope_note"]


async def test_a_countys_own_calendar_is_covered_outright():
    env = await search_meetings(_ctx(EmptyFetcher()), "Albemarle County",
                                **BUSY)
    assert env.coverage.registry.value == "covered"
    assert env.coverage.jurisdictions_unavailable == []
    assert "scope_note" not in env.data["results"][0]


async def test_a_town_with_no_covered_parent_is_still_a_plain_gap():
    """Leesburg sits in Loudoun County, which is not on the platform. No
    calendar was borrowed, so nothing is partial: the answer is the
    registry gap it always was."""
    env = await search_meetings(_ctx(EmptyFetcher()), "Leesburg", **BUSY)
    assert env.coverage.registry.value == "none"
    assert env.data["results"] == []


# --- the inline cap --------------------------------------------------------

async def test_a_long_window_is_cut_inline_and_kept_whole_in_the_store():
    total = INLINE_RECORD_CAP + 15
    ctx = _ctx(ManyFetcher(total))
    env = await search_meetings(ctx, "Richmond City", **BUSY)
    block = env.data["results"][0]
    assert len(block["records"]) == INLINE_RECORD_CAP
    assert block["record_count"] == total
    assert "truncated_inline" in {w.code.value for w in env.warnings}
    handle = block["full_records_ref"]
    assert handle.startswith("commonwealth://")
    assert [r.uri for r in env.resources] == [handle]
    stored = ctx.results.get(handle)
    assert stored.payload["record_count"] == total
    assert len(stored.payload["records"]) == total
    # Evidence covers what is shown: one entry per inline record.
    assert len(env.evidence) == INLINE_RECORD_CAP
    assert all(r["evidence_refs"] for r in block["records"])


async def test_a_window_within_the_cap_is_shown_whole():
    env = await search_meetings(_ctx(ManyFetcher(INLINE_RECORD_CAP)),
                                "Richmond City", **BUSY)
    block = env.data["results"][0]
    assert len(block["records"]) == block["record_count"] == INLINE_RECORD_CAP
    assert "full_records_ref" not in block
    assert "truncated_inline" not in {w.code.value for w in env.warnings}
    assert env.resources == []
