"""Civic resilience tier: an outage is an outage, never an empty result."""
from commonwealth.core.errors import SourceUnavailable
from commonwealth.domains.civic import browse_code, get_code_section
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


class ApiOutageFetcher:
    async def fetch_json(self, url: str, params: dict) -> dict:
        raise SourceUnavailable("simulated outage (HTTP 503 after retry)")


async def test_a_browse_outage_is_failed_execution_not_an_empty_code():
    """An unreachable table of contents must not read as a Code with no
    titles in it. That is the same distinction the section lookup makes,
    one level up."""
    ctx = build_ctx(civic_api_fetcher=ApiOutageFetcher())
    env = await browse_code(ctx)
    assert env.coverage.execution.value == "failed"
    assert env.coverage.result.value == "empty"
    assert env.coverage.registry.value == "covered", "an outage is not a gap"
    assert [f.error for f in env.coverage.source_failures] == [
        "SourceUnavailable"]
    assert env.data["results"] == []


async def test_the_two_civic_paths_fail_independently():
    """Section text is HTML and the contents listing is JSON, from one
    publisher over two endpoints. A redesign of the site's markup should
    not take the walk down with it, and an API outage should not stop a
    caller who already has a citation."""
    html_down = build_ctx(civic_fetcher=OutageFetcher())
    assert (await browse_code(html_down)).coverage.execution.value == \
        "complete", "the walk does not read the HTML pages"

    api_down = build_ctx(civic_api_fetcher=ApiOutageFetcher())
    env = await get_code_section(api_down, citation="1-500")
    assert env.coverage.execution.value == "complete", (
        "a citation lookup does not read the JSON API")
    assert env.data["results"][0]["found"] is True
