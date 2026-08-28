"""Registry tools answer from project data, so their resilience tier is
about degraded project state: empty registries and inconsistent tables must
fail or report honestly, never crash or invent."""
import pytest

from commonwealth.adapters.arcgis import ArcGISAdapter
from commonwealth.adapters.base import TTLCache
from commonwealth.core.jurisdiction import JurisdictionTable
from commonwealth.core.registry import SourceRegistry
from commonwealth.domains.registry import search_sources, source_status
from commonwealth.runtime import SOURCES_DIR, RuntimeContext
from tests.conftest import ReplayFetcher, load_recording


def _ctx_with_zero_manifests() -> RuntimeContext:
    real = SourceRegistry.load(SOURCES_DIR)
    return RuntimeContext(
        sources=SourceRegistry([], real.capability_vocab, "empty"),
        jurisdictions=JurisdictionTable.load(SOURCES_DIR / "jurisdictions"),
        arcgis=ArcGISAdapter(
            fetcher=ReplayFetcher(load_recording()["exchanges"]),
            cache=TTLCache()))


async def test_zero_manifest_registry_reports_empty_not_crash():
    ctx = _ctx_with_zero_manifests()
    env = await search_sources(ctx, capability="zoning.lookup")
    assert env.data["record_count"] == 0
    assert env.coverage.result.value == "empty"
    env2 = await source_status(ctx)
    assert env2.data["record_count"] == 0


def test_empty_jurisdiction_directory_refuses_to_load(tmp_path):
    with pytest.raises(FileNotFoundError, match="load-bearing"):
        JurisdictionTable.load(tmp_path)


def test_missing_capability_vocab_refuses_to_load(tmp_path):
    with pytest.raises(FileNotFoundError, match="capability vocabulary"):
        SourceRegistry.load(tmp_path)
