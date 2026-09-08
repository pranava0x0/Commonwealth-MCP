"""Civic resilience tier: an outage is an outage, never an empty result."""
import pytest

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


async def test_a_payload_without_its_listing_key_is_an_outage():
    """The publisher sends `ChapterList` even for a title it does not
    have — an unknown title is `{"TitleNumber": null, "ChapterList": []}`.
    So a document without the key is one this parser does not recognise,
    and calling it an empty branch of the Code would report a complete
    execution over a payload nobody understood."""
    from commonwealth.adapters.replay import ReplayFetcher

    exchanges = [{"url": "https://law.lis.virginia.gov/api/"
                         "CoVChaptersGetListOfJson/15.2",
                  "params": {},
                  # An HTTP 200 error object, which is how this service
                  # reports at least one of its failures.
                  "response": {"Message": "An error has occurred."}}]
    ctx = build_ctx(civic_api_fetcher=ReplayFetcher(exchanges))
    env = await browse_code(ctx, title="15.2")
    assert env.coverage.execution.value == "failed"
    assert env.coverage.result.value == "empty"
    assert [f.error for f in env.coverage.source_failures] == [
        "SourceUnavailable"]
    assert env.data["results"] == []


async def test_an_explicit_empty_listing_is_still_a_clean_empty():
    """The other side of it: the publisher's own way of saying a branch
    has nothing under it must not be read as an outage."""
    from commonwealth.adapters.replay import ReplayFetcher

    exchanges = [{"url": "https://law.lis.virginia.gov/api/"
                         "CoVChaptersGetListOfJson/99.9",
                  "params": {},
                  "response": {"TitleNumber": None, "TitleName": None,
                               "ChapterList": []}}]
    ctx = build_ctx(civic_api_fetcher=ReplayFetcher(exchanges))
    env = await browse_code(ctx, title="99.9")
    assert env.coverage.execution.value == "complete"
    assert env.coverage.result.value == "empty"
    assert env.coverage.source_failures == []


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


async def test_the_health_probe_covers_both_endpoints():
    """The source has two endpoints that fail independently, and a probe
    that read only the section pages called it healthy while
    `civic.browse_code` was down for everyone. `doctor --live` and
    `sources probe` both dispatch through this."""
    from commonwealth.core.registry import SourceRegistry
    from commonwealth.runtime import SOURCES_DIR

    m = SourceRegistry.load(SOURCES_DIR).get("va-code-of-virginia")
    assert m.health.expect.get("known_title"), (
        "the manifest must declare a title for the browse half of the probe")

    ctx = build_ctx()
    result = await ctx.virginia_law.health(
        m, m.health.expect["known_section"], m.health.expect["known_title"])
    assert result["section"]["found"] is True
    assert result["browse"]["found"] is True
    assert result["browse"]["chapters"] > 0


async def test_the_probe_fails_when_only_the_json_api_is_down():
    """The case the probe existed to miss: the pages answer, the API does
    not, and the source is not healthy."""
    ctx = build_ctx(civic_api_fetcher=ApiOutageFetcher())
    m = ctx.sources.get("va-code-of-virginia")
    with pytest.raises(SourceUnavailable):
        await ctx.virginia_law.health(m, m.health.expect["known_section"],
                                      m.health.expect["known_title"])

    # And the other way round, so the two halves are really independent.
    ctx = build_ctx(civic_fetcher=OutageFetcher())
    with pytest.raises(SourceUnavailable):
        await ctx.virginia_law.health(m, m.health.expect["known_section"],
                                      m.health.expect["known_title"])
