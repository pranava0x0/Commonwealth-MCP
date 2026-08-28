"""Civic resilience tier: an outage is an outage, never an empty result."""
from commonwealth.core.errors import SourceUnavailable
from commonwealth.domains.civic import get_code_section
from tests.conftest import build_ctx


class OutageFetcher:
    async def fetch_html(self, url: str) -> tuple[str, str]:
        raise SourceUnavailable("simulated outage (HTTP 503 after retry)")


async def test_total_outage_is_failed_execution_not_empty():
    ctx = build_ctx(civic_fetcher=OutageFetcher())
    env = await get_code_section(ctx, citation="1-500")
    assert env.coverage.execution.value == "failed"
    assert env.coverage.result.value == "empty"
    assert env.coverage.registry.value == "covered", "an outage is not a gap"
    assert [f.error for f in env.coverage.source_failures] == [
        "SourceUnavailable"]
    assert env.data["results"] == []


async def test_recovers_once_the_fetcher_is_healthy_again():
    """Not a real retry — proves the outage above was fetcher-specific,
    not a bug that always breaks the tool."""
    ctx = build_ctx()  # default replay fetcher, healthy
    env = await get_code_section(ctx, citation="1-500")
    assert env.coverage.execution.value == "complete"
    assert env.coverage.result.value == "hit"
