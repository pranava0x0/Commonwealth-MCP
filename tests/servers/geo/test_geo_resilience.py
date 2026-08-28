"""Geo resilience tier: outages are outages, never empty results."""
from commonwealth.core.errors import SourceUnavailable
from commonwealth.domains.geo import find_zoning
from tests.conftest import (SECONDARY_URL, ReplayFetcher, build_ctx,
                            load_recording, make_secondary_manifest,
                            secondary_exchanges)


class OutageFetcher:
    """Fails requests to chosen hosts; delegates the rest to replay."""

    def __init__(self, fail_substring: str, exchanges: list[dict]) -> None:
        self.fail_substring = fail_substring
        self.replay = ReplayFetcher(exchanges)

    async def fetch_json(self, url: str, params: dict) -> dict:
        if self.fail_substring in url:
            raise SourceUnavailable(
                "simulated outage (HTTP 503 after retry)")
        return await self.replay.fetch_json(url, params)


async def test_total_outage_is_failed_execution_not_empty(sample_pin):
    ctx = build_ctx(fetcher=OutageFetcher("fairfaxcounty.gov",
                                          load_recording()["exchanges"]))
    env = await find_zoning(ctx, jurisdiction="Fairfax County",
                            pin=sample_pin)
    assert env.coverage.execution.value == "failed"
    assert env.coverage.result.value == "empty"
    assert env.coverage.registry.value == "covered", (
        "an outage is not a registry gap")
    assert [f.error for f in env.coverage.source_failures] == [
        "SourceUnavailable"]
    assert env.data["results"] == []


async def test_one_of_two_down_is_partial_with_the_survivor(sample_pin):
    exchanges = load_recording()["exchanges"] + secondary_exchanges()
    ctx = build_ctx(extra_manifests=[make_secondary_manifest()],
                    extra_exchanges=secondary_exchanges(),
                    fetcher=OutageFetcher(SECONDARY_URL, exchanges))
    env = await find_zoning(ctx, jurisdiction="Fairfax County",
                            pin=sample_pin)
    assert env.coverage.execution.value == "partial"
    assert env.coverage.result.value == "hit", "the survivor's answer stands"
    assert len(env.data["results"]) == 1
    failed = {f.source_id for f in env.coverage.source_failures}
    assert failed == {"va-fairfax-secondary-mirror"}
