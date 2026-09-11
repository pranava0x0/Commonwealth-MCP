"""Meetings unit tier: the adapter's own decisions, below the envelope.

The date-window rules, the prose cancellation reading, and the record
mapping — each tested against the recorded payload rather than a
hand-written shape.
"""
import json
import pathlib

import pytest

from commonwealth.adapters.agenda_platform import (MAX_RANGE_DAYS,
                                                   AgendaPlatformAdapter,
                                                   _cancellation_note,
                                                   check_range)
from commonwealth.core.errors import InvalidQuery, SourceUnavailable

FIXTURES = pathlib.Path(__file__).parents[2] / "fixtures" / "sources"


def _recorded(source_id: str) -> dict:
    return json.loads((FIXTURES / source_id / "recorded.json").read_text())


# --- the date window -------------------------------------------------------

def test_a_valid_window_comes_back_as_dates():
    start, end = check_range("2026-09-01", "2026-09-30")
    assert (start.isoformat(), end.isoformat()) == ("2026-09-01", "2026-09-30")


def test_a_single_day_is_a_valid_window():
    start, end = check_range("2026-09-01", "2026-09-01")
    assert start == end


@pytest.mark.parametrize("start,end", [
    ("2026-09-30", "2026-09-01"),      # backwards
    ("Sept 1", "2026-09-30"),          # not ISO
    ("2026-09-01", ""),                # missing
    ("2026-13-01", "2026-13-05"),      # not a real month
    ("2026-02-30", "2026-03-01"),      # not a real day
])
def test_a_window_that_is_not_one_is_refused(start, end):
    with pytest.raises(InvalidQuery):
        check_range(start, end)


def test_the_last_expressible_date_is_refused_rather_than_overflowing():
    """The publisher's filter is half-open, so the query asks for the day
    AFTER `end_date`. At date.max that raises OverflowError, which is not
    a CommonwealthError — it would escape the domain and server wrappers
    as an untyped internal failure, past the audit path a typed error
    takes. Found in review of PR #56."""
    from datetime import date

    with pytest.raises(InvalidQuery) as err:
        check_range("9999-12-31", "9999-12-31")
    assert "ends earlier" in str(err.value)
    # And the day before it is still a perfectly good window, so the
    # guard is a boundary rather than a horizon.
    start, end = check_range("9999-12-29", "9999-12-30")
    assert end < date.max


async def test_an_overflowing_window_is_a_typed_error_through_the_tool():
    """The whole point of the guard: the caller gets InvalidQuery, not a
    500 from an OverflowError nobody catches."""
    from commonwealth.domains.civic import search_meetings
    from tests.conftest import build_ctx

    with pytest.raises(InvalidQuery):
        await search_meetings(build_ctx(), "Richmond City",
                              start_date="9999-12-31", end_date="9999-12-31")


def test_an_overlong_window_names_the_limit_rather_than_truncating():
    """The failure mode is a silent default, so the error has to say what
    the limit is and that there is no default to fall back to."""
    with pytest.raises(InvalidQuery) as err:
        check_range("2026-01-01", "2029-01-01")
    message = str(err.value)
    assert str(MAX_RANGE_DAYS) in message
    assert "no default range" in message


def test_the_limit_boundary_is_inclusive():
    """Exactly MAX_RANGE_DAYS is allowed; one more is not. Pinned because
    an off-by-one here silently moves a published limit."""
    from datetime import date, timedelta

    start = date(2026, 1, 1)
    ok = start + timedelta(days=MAX_RANGE_DAYS - 1)
    check_range(start.isoformat(), ok.isoformat())
    with pytest.raises(InvalidQuery):
        check_range(start.isoformat(),
                    (ok + timedelta(days=1)).isoformat())


# --- the cancellation reading ---------------------------------------------

@pytest.mark.parametrize("comment", [
    "This meeting has been cancelled.",
    "CANCELLED Navy Hill Development Proposal Work Session",
    "**This meeting has been cancelled**",
    "MEETING CANCELED",                       # one L, as one locality spells it
    "The March 16, 2020 BZA Hearing has been cancelled.",
])
def test_a_comment_saying_cancelled_is_read_as_one(comment):
    note = _cancellation_note(comment)
    assert note is not None
    assert "cancelled" in note


def test_a_rescheduled_comment_is_read_as_rescheduled():
    note = _cancellation_note("This meeting has been rescheduled to May 4.")
    assert note is not None and "rescheduled" in note


@pytest.mark.parametrize("comment", [
    "",
    "To access the meeting via Teams, use the following link",
    "Docket items may be deferred at the request of the applicant.",
    # The word inside another word must not trip it: this is why the
    # pattern is anchored on word boundaries rather than a substring.
    "The cancellation policy for room bookings is posted separately.",
])
def test_an_ordinary_comment_is_not_read_as_a_cancellation(comment):
    if "cancellation policy" in comment:
        # Honest exception: this one DOES contain the word, and the
        # reading is deliberately generous — a false positive here costs
        # a caller a second look, a false negative costs them a meeting
        # they thought was happening. Recorded rather than hidden.
        assert _cancellation_note(comment) is not None
        return
    assert _cancellation_note(comment) is None


def test_the_note_never_claims_the_publisher_said_it():
    note = _cancellation_note("This meeting has been cancelled.")
    assert "publishes no cancellation field" in note
    assert "not from a status the publisher set" in note


# --- the record mapping ----------------------------------------------------

def _one_recorded_window(source_id: str):
    """The busiest recorded exchange for a source, as the publisher sent
    it — no hand-written meeting shapes anywhere in this tier."""
    exchanges = _recorded(source_id)["exchanges"]
    return max((e["response"] for e in exchanges), key=len)


def test_the_recorded_payload_has_no_cancellation_field_at_all():
    """The finding the whole prose-reading path exists for, pinned against
    the recording so a platform that later adds a real field shows up
    here as a failing test rather than as silence."""
    rows = _one_recorded_window("va-richmond-city-meetings")
    statuses = {r.get("EventAgendaStatusName") for r in rows}
    assert statuses <= {"Final", "Final-revised"}, (
        "the platform has started publishing a new agenda status; if one "
        "of them means 'cancelled', read it instead of the comment prose")
    assert not any("cancel" in key.lower() for row in rows for key in row)


async def test_a_row_maps_to_the_publishers_own_values():
    from commonwealth.core.registry import SourceRegistry
    from commonwealth.runtime import SOURCES_DIR
    from commonwealth.adapters.replay import ReplayFetcher

    registry = SourceRegistry.load(SOURCES_DIR)
    manifest = registry.get("va-richmond-city-meetings")
    exchanges = _recorded("va-richmond-city-meetings")["exchanges"]
    adapter = AgendaPlatformAdapter(fetcher=ReplayFetcher(exchanges))
    meetings, url = await adapter.search_meetings(
        manifest, "2026-09-01", "2026-09-30")

    assert "richmondva" in url
    rows = _one_recorded_window("va-richmond-city-meetings")
    by_id = {str(r["EventId"]): r for r in rows}
    for m in meetings:
        row = by_id[m.event_id]
        # Stripped, not reworded: this publisher pads some body names
        # with trailing whitespace ("...Standing Committee "), and
        # trimming it is the only change made to any published string.
        assert m.body == row["EventBodyName"].strip()
        # The date half only: the publisher's datetime is always
        # midnight and the real time is the separate string.
        assert m.meeting_date == row["EventDate"][:10]
        assert m.meeting_time == (row["EventTime"] or "")
        assert m.agenda_url == (row["EventAgendaFile"] or None)


async def test_a_body_filter_narrows_without_reordering():
    from commonwealth.core.registry import SourceRegistry
    from commonwealth.runtime import SOURCES_DIR
    from commonwealth.adapters.replay import ReplayFetcher

    registry = SourceRegistry.load(SOURCES_DIR)
    manifest = registry.get("va-richmond-city-meetings")
    exchanges = _recorded("va-richmond-city-meetings")["exchanges"]
    adapter = AgendaPlatformAdapter(fetcher=ReplayFetcher(exchanges))

    everything, _ = await adapter.search_meetings(
        manifest, "2026-09-01", "2026-09-30")
    planning, _ = await adapter.search_meetings(
        manifest, "2026-09-01", "2026-09-30", body="planning")

    assert planning, "the recorded window has a Planning Commission meeting"
    assert all("planning" in m.body.casefold() for m in planning)
    # A subsequence of the unfiltered answer, in the publisher's order:
    # narrowing is allowed, re-ranking is not.
    assert [m.event_id for m in planning] == [
        m.event_id for m in everything
        if "planning" in m.body.casefold()]


async def test_a_bad_client_identifier_never_becomes_a_path():
    """The manifest supplies this, so a malicious value means a bad
    manifest — but a client of `../../v1/other` would read a different
    locality's calendar and report it under this manifest's name."""
    from commonwealth.core.registry import SourceRegistry
    from commonwealth.runtime import SOURCES_DIR
    from commonwealth.adapters.replay import ReplayFetcher

    registry = SourceRegistry.load(SOURCES_DIR)
    manifest = registry.get("va-richmond-city-meetings").model_copy(deep=True)
    manifest.adapter.client = "../../v1/alexandria"
    exchanges = _recorded("va-richmond-city-meetings")["exchanges"]
    adapter = AgendaPlatformAdapter(fetcher=ReplayFetcher(exchanges))
    with pytest.raises(InvalidQuery):
        await adapter.search_meetings(manifest, "2026-09-01", "2026-09-30")


async def test_a_list_of_non_objects_is_an_outage_not_an_empty_calendar():
    from commonwealth.core.registry import SourceRegistry
    from commonwealth.runtime import SOURCES_DIR

    class JunkFetcher:
        async def fetch_json_list(self, url, params):
            return ["not", "meeting", "records"]

    registry = SourceRegistry.load(SOURCES_DIR)
    manifest = registry.get("va-richmond-city-meetings")
    adapter = AgendaPlatformAdapter(fetcher=JunkFetcher())
    with pytest.raises(SourceUnavailable):
        await adapter.search_meetings(manifest, "2026-09-01", "2026-09-30")


# --- the publisher's freshness signal (Codex review, PR #56) ---------------

@pytest.mark.parametrize("raw,expected", [
    ("2026-09-08T14:17:05.757", "2026-09-08T14:17:05Z"),
    ("2014-05-24T04:17:58.883", "2014-05-24T04:17:58Z"),
    ("2026-09-08T14:17:05Z", "2026-09-08T14:17:05Z"),
])
def test_a_publisher_timestamp_is_normalised_not_reformatted(raw, expected):
    from commonwealth.adapters.agenda_platform import _utc

    assert _utc(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "not a date", "2026-13-45T00:00:00"])
def test_an_unparseable_timestamp_becomes_none_rather_than_a_guess(raw):
    """A freshness claim invented from a string nobody could parse is
    worse than admitting the vintage is unknown."""
    from commonwealth.adapters.agenda_platform import _utc

    assert _utc(raw) is None


async def test_every_meeting_carries_the_publishers_last_edit():
    from commonwealth.core.registry import SourceRegistry
    from commonwealth.runtime import SOURCES_DIR
    from commonwealth.adapters.replay import ReplayFetcher

    registry = SourceRegistry.load(SOURCES_DIR)
    manifest = registry.get("va-richmond-city-meetings")
    exchanges = _recorded("va-richmond-city-meetings")["exchanges"]
    adapter = AgendaPlatformAdapter(fetcher=ReplayFetcher(exchanges))
    meetings, _ = await adapter.search_meetings(
        manifest, "2026-09-01", "2026-09-30")

    rows = {str(r["EventId"]): r for r in _one_recorded_window(
        "va-richmond-city-meetings")}
    assert meetings
    for m in meetings:
        raw = rows[m.event_id]["EventLastModifiedUtc"]
        assert m.last_modified is not None, (
            "the publisher sent a last-modified timestamp and it was "
            "dropped; it is the only freshness signal this platform has")
        assert m.last_modified.startswith(raw[:19])
