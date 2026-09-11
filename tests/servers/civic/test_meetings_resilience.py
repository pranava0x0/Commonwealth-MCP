"""Meetings resilience tier: an outage is an outage, never a quiet
calendar.

The whole point of this tool is that a locality's meetings are readable.
Every failure shape here has the same job — to come back as something a
caller cannot mistake for "this government is not meeting".
"""
import pytest

from commonwealth.core.errors import (InvalidQuery, RateLimited,
                                      SourceUnavailable)
from commonwealth.domains.civic import search_meetings
from tests.conftest import build_ctx

BUSY = {"start_date": "2026-09-01", "end_date": "2026-09-30"}


class OutageFetcher:
    async def fetch_json_list(self, url, params):
        raise SourceUnavailable("simulated outage (HTTP 503 after retry)")


class RateLimitedFetcher:
    async def fetch_json_list(self, url, params):
        raise RateLimited("simulated 429", 30)


async def test_a_total_outage_is_failed_execution_not_an_empty_calendar():
    ctx = build_ctx(agenda_fetcher=OutageFetcher())
    env = await search_meetings(ctx, "Richmond City", **BUSY)
    assert env.coverage.execution.value == "failed"
    assert env.coverage.result.value == "empty"
    # The locality IS covered. An outage must never be reported as a
    # registry gap, or the fix looks like "register a source" when the
    # source is registered and down.
    assert env.coverage.registry.value == "covered"
    assert [f.error for f in env.coverage.source_failures] == [
        "SourceUnavailable"]
    assert env.data["results"] == []


async def test_rate_limiting_is_its_own_failure_not_an_empty_window():
    ctx = build_ctx(agenda_fetcher=RateLimitedFetcher())
    env = await search_meetings(ctx, "Richmond City", **BUSY)
    assert env.coverage.execution.value == "failed"
    assert [f.error for f in env.coverage.source_failures] == ["RateLimited"]


async def test_an_outage_and_a_gap_are_distinguishable():
    """The pair that matters most. Both return no records; only one of
    them means a source exists and is broken."""
    down = await search_meetings(
        build_ctx(agenda_fetcher=OutageFetcher()), "Richmond City", **BUSY)
    gap = await search_meetings(build_ctx(), "Fairfax County", **BUSY)
    assert down.coverage.result.value == gap.coverage.result.value == "empty"
    assert down.coverage.registry.value == "covered"
    assert gap.coverage.registry.value == "none"
    assert down.coverage.source_failures and not gap.coverage.source_failures


async def test_recovers_once_the_fetcher_is_healthy_again():
    """Proves the outage above was fetcher-specific, not a tool that is
    always broken."""
    env = await search_meetings(build_ctx(), "Richmond City", **BUSY)
    assert env.coverage.execution.value == "complete"
    assert env.coverage.result.value == "hit"


class GarbledFetcher:
    """HTTP 200 with something that is not the documented array."""

    async def fetch_json_list(self, url, params):
        raise SourceUnavailable(
            "webapi.legistar.com returned dict, not the JSON array this "
            "endpoint documents.")


async def test_a_changed_response_shape_is_an_outage_not_an_empty_calendar():
    ctx = build_ctx(agenda_fetcher=GarbledFetcher())
    env = await search_meetings(ctx, "Richmond City", **BUSY)
    assert env.coverage.execution.value == "failed"
    assert env.data["results"] == []


async def test_a_bad_window_is_refused_before_any_source_is_touched():
    """An argument error is the caller's, and must not be recorded as the
    publisher failing. Asserted against a fetcher that would raise if it
    were reached at all."""
    class NeverCalled:
        async def fetch_json_list(self, url, params):
            raise AssertionError("the window should have been refused first")

    ctx = build_ctx(agenda_fetcher=NeverCalled())
    with pytest.raises(InvalidQuery):
        await search_meetings(ctx, "Richmond City",
                              start_date="2026-01-01", end_date="2029-01-01")


async def test_a_bad_window_is_refused_even_where_there_is_no_source():
    """Order matters: the argument check runs before jurisdiction
    resolution and before selection, so the caller gets the real
    complaint rather than a registry gap that hides it."""
    ctx = build_ctx()
    with pytest.raises(InvalidQuery):
        await search_meetings(ctx, "Fairfax County",
                              start_date="2026-01-01", end_date="2029-01-01")
