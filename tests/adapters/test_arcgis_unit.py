"""ArcGIS adapter over recorded exchanges (never synthesized shapes)."""
import json

import pytest
from pydantic import ValidationError

from commonwealth.adapters.arcgis import ArcGISAdapter, ArcGISParams
from commonwealth.adapters.base import TTLCache
from commonwealth.core.errors import InvalidQuery, SourceUnavailable
from commonwealth.core.registry import SourceManifest
from tests.conftest import ReplayFetcher, _real_manifest, load_recording


def test_cross_host_layer_override_is_rejected():
    """A layer service_url on a different host than the manifest's
    top-level one would be refused live by the egress policy (its host
    allowlist is derived from the top-level service_url only) — this must
    fail manifest validation instead of only failing the first live query."""
    m = _real_manifest().model_dump()["adapter"]
    m["layers"]["zoning"]["service_url"] = (
        "https://services1.arcgis.com/FAKE/ZoningDistricts/FeatureServer")
    with pytest.raises(ValidationError, match="does not match"):
        ArcGISParams.model_validate({k: v for k, v in m.items()
                                     if k != "type"})


@pytest.fixture()
def adapter() -> ArcGISAdapter:
    return ArcGISAdapter(fetcher=ReplayFetcher(load_recording()["exchanges"]),
                         cache=TTLCache())


async def test_sensitive_public_filters_before_cache_and_mapping():
    """../../design/architecture.md decision 0014 § 3: exposure_allowlist must actually filter the
    response before it is cached or mapped into a canonical record — a
    field the reviewer never allowlisted must never leave the adapter,
    not even as a `raw` value on the evidence path."""
    m = _real_manifest().model_dump()
    m["access"]["data_classification"] = "sensitive_public"
    m["access"]["exposure_allowlist"] = ["PIN"]
    m["access"]["classification_reviewed_by"] = "test"
    m["access"]["classification_reviewed_at"] = "2026-08-28"
    manifest = SourceManifest.model_validate(m)

    class FakeFetcher:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch_json(self, url, params):
            self.calls += 1
            return {"features": [{"attributes": {
                "OBJECTID": 1, "PIN": "0102 14  0231",
                "PARCEL_TYPE": "not on the allowlist"}}]}

    fetcher = FakeFetcher()
    adapter = ArcGISAdapter(fetcher=fetcher, cache=TTLCache())
    q = await adapter.query(manifest, "parcels",
                            where_equals={"pin": "0102 14  0231"})
    rec = q.records[0]
    assert rec.raw == {"OBJECTID": 1, "PIN": "0102 14  0231"}, (
        "PARCEL_TYPE is not allowlisted and must be dropped from raw, even "
        "though id_field (OBJECTID) is always retained")
    assert rec.canonical["parcel_type"] is None, (
        "a canonical field mapped from a non-allowlisted source field must "
        "come back empty, not leak the value")


async def test_query_by_pin_maps_canonical_fields(adapter, sample_pin):
    m = _real_manifest()
    q = await adapter.query(m, "parcels", where_equals={"pin": sample_pin})
    assert q.records, "recorded PIN query must return the recorded parcel"
    rec = q.records[0]
    assert rec.canonical["pin"] == sample_pin
    assert rec.record_id.startswith("OBJECTID:")
    assert "PIN" in rec.raw, "raw source fields stay available"
    assert q.transformations == ["field_mapping:v1"]
    assert q.payload_hash().startswith("sha256:")


async def test_unknown_canonical_field_is_invalid_query(adapter):
    with pytest.raises(InvalidQuery, match="not mapped"):
        await adapter.query(_real_manifest(), "parcels",
                            where_equals={"nope": "x"})


async def test_unknown_layer_is_invalid_query(adapter):
    with pytest.raises(InvalidQuery, match="declares no layer"):
        await adapter.query(_real_manifest(), "wells",
                            where_equals={"pin": "x"})


async def test_unbounded_query_refused(adapter):
    with pytest.raises(InvalidQuery, match="unbounded"):
        await adapter.query(_real_manifest(), "parcels")


async def test_error_body_raises_typed_error(project_root):
    """Real recorded 200-with-error-body (tests/fixtures/arcgis-error-body.json,
    recorded live 2026-08-27 from the Fairfax service)."""
    error_body = json.loads(
        (project_root / "tests" / "fixtures" /
         "arcgis-error-body.json").read_text())

    class ErrorFetcher:
        async def fetch_json(self, url, params):
            return error_body

    adapter = ArcGISAdapter(fetcher=ErrorFetcher(), cache=TTLCache())
    with pytest.raises(InvalidQuery, match="ArcGIS rejected"):
        await adapter.query(_real_manifest(), "parcels",
                            where_equals={"pin": "x"})


async def test_missing_features_key_is_schema_change():
    class WeirdFetcher:
        async def fetch_json(self, url, params):
            return {"unexpected": True}

    adapter = ArcGISAdapter(fetcher=WeirdFetcher(), cache=TTLCache())
    with pytest.raises(SourceUnavailable, match="no `features` key"):
        await adapter.query(_real_manifest(), "parcels",
                            where_equals={"pin": "x"})


async def test_cache_serves_second_call_without_refetch(sample_pin):
    fetcher = ReplayFetcher(load_recording()["exchanges"])
    adapter = ArcGISAdapter(fetcher=fetcher, cache=TTLCache())
    m = _real_manifest()
    q1 = await adapter.query(m, "parcels", where_equals={"pin": sample_pin})
    calls_after_first = len(fetcher.calls)
    q2 = await adapter.query(m, "parcels", where_equals={"pin": sample_pin})
    assert len(fetcher.calls) == calls_after_first, "second call must be cached"
    assert q2.cache_age_seconds >= 0
    # A cache hit under one second old still truncates cache_age_seconds to
    # 0 — indistinguishable from a fresh fetch by age alone. from_cache is
    # the explicit signal geo.py's access_path derivation actually needs.
    assert q1.from_cache is False, "the first call is a fresh fetch"
    assert q2.from_cache is True, "the second call must be flagged as cached"


async def test_layer_service_url_override_wins_over_top_level(sample_pin):
    """Some publishers split layers across separate FeatureServers (Richmond
    City: Parcels and ZoningDistricts are two services, not two layers of
    one service like Fairfax). A layer's own service_url must win; a layer
    with no override must still use the manifest's top-level default."""
    m = _real_manifest().model_dump()
    # Same host as the top-level service_url, different path — a layer
    # override must stay on-host (ArcGISParams validates this; the egress
    # policy's host allowlist is derived from the top-level service_url
    # only, so a genuinely cross-host split needs a manifest-level egress
    # change too, not just this field).
    override_url = ("https://www.fairfaxcounty.gov/mercator/rest/services/"
                    "OpenData/ZoningOnly/FeatureServer")
    m["adapter"]["layers"]["zoning"]["service_url"] = override_url
    manifest = SourceManifest.model_validate(m)

    class RecordingFetcher:
        def __init__(self) -> None:
            self.urls: list[str] = []

        async def fetch_json(self, url, params):
            self.urls.append(url)
            return {"features": []}

    fetcher = RecordingFetcher()
    adapter = ArcGISAdapter(fetcher=fetcher, cache=TTLCache())

    await adapter.query(manifest, "zoning", where_equals={"district": "R-1"})
    assert fetcher.urls[-1].startswith(override_url), (
        "the zoning layer's own service_url must be used, not the "
        "manifest's top-level default")

    await adapter.query(manifest, "parcels", where_equals={"pin": "x"})
    assert fetcher.urls[-1].startswith(
        _real_manifest().adapter.model_dump()["service_url"]), (
        "a layer with no override must still use the top-level default")


async def test_where_value_quotes_are_escaped(adapter, sample_pin):
    """The escape path: a quoted value must not truncate the clause. The
    replay map has no such exchange, so the assertion is on the URL the
    adapter TRIED — the loud replay miss carries the built clause."""
    with pytest.raises(AssertionError, match=r"O''Brien"):
        await adapter.query(_real_manifest(), "parcels",
                            where_equals={"pin": "O'Brien"})


# --------------------------------------------------------------------------
# Pagination (GitHub issue #34). A query used to return the service's first
# page and report `pagination: truncated` when more remained. Accurate, and
# still a partial answer.
#
# ReplayFetcher needs an exact recorded exchange per request, so these use a
# purpose-built fake that behaves like a paging FeatureServer.
# --------------------------------------------------------------------------
from commonwealth.adapters.arcgis import MAX_QUERY_PAGES


class _PagingService:
    """An ArcGIS layer holding `total` rows and serving `page_size` at a
    time, exactly as the platform does: honour resultOffset, and set
    exceededTransferLimit whenever rows remain."""

    def __init__(self, total: int, page_size: int = 50,
                 supports_pagination: bool = True):
        self.total, self.page_size = total, page_size
        self.supports_pagination = supports_pagination
        # A layer can advertise pagination and still ignore resultOffset.
        self.honours_offset = True
        self.offsets: list[int] = []

    async def fetch_json(self, url: str, params: dict) -> dict:
        if not url.endswith("/query"):
            return {                     # layer_info
                "editingInfo": {"lastEditDate": 1_700_000_000_000},
                "advancedQueryCapabilities": {
                    "supportsPagination": self.supports_pagination},
            }
        offset = int(params.get("resultOffset", 0))
        self.offsets.append(offset)
        if not (self.supports_pagination and self.honours_offset):
            offset = 0                   # a service that ignores the param
        size = int(params.get("resultRecordCount", self.page_size))
        rows = range(offset, min(offset + size, self.total))
        return {
            "features": [
                {"attributes": {"OBJECTID": i, "PIN": f"pin-{i}"}}
                for i in rows
            ],
            "exceededTransferLimit": offset + size < self.total,
        }


def _paging_adapter(service: _PagingService) -> ArcGISAdapter:
    return ArcGISAdapter(fetcher=service, cache=TTLCache())


async def test_a_single_page_result_is_not_called_truncated():
    svc = _PagingService(total=30)
    result = await _paging_adapter(svc).query(
        _real_manifest(), "parcels", where_equals={"pin": "x"})
    assert len(result.records) == 30
    assert result.exceeded_transfer_limit is False
    assert svc.offsets == [0], "asked for a second page it did not need"


async def test_pages_are_followed_until_the_rows_run_out():
    svc = _PagingService(total=120)      # three pages at 50
    result = await _paging_adapter(svc).query(
        _real_manifest(), "parcels", where_equals={"pin": "x"})
    assert len(result.records) == 120
    assert result.exceeded_transfer_limit is False, (
        "paged to completion, so nothing remains to report as truncated")
    assert svc.offsets == [0, 50, 100]


async def test_the_page_budget_bounds_the_walk_and_still_reports_truncation():
    """Each page is another request to a government service, so the walk is
    bounded. Hitting the bound is the case that must still say truncated."""
    svc = _PagingService(total=10_000)
    result = await _paging_adapter(svc).query(
        _real_manifest(), "parcels", where_equals={"pin": "x"})
    assert len(svc.offsets) == MAX_QUERY_PAGES
    assert result.exceeded_transfer_limit is True
    assert len(result.records) == MAX_QUERY_PAGES * 50


async def test_a_service_without_paging_support_is_not_paged():
    """resultOffset on a layer that does not advertise pagination returns
    the first page again. Walking that would duplicate every row."""
    svc = _PagingService(total=10_000, supports_pagination=False)
    result = await _paging_adapter(svc).query(
        _real_manifest(), "parcels", where_equals={"pin": "x"})
    assert svc.offsets == [0]
    assert result.exceeded_transfer_limit is True
    assert len(result.records) == 50


async def test_paging_is_recorded_in_transformations():
    """A caller reading the envelope can see the answer was assembled from
    several responses rather than returned by one."""
    svc = _PagingService(total=120)
    result = await _paging_adapter(svc).query(
        _real_manifest(), "parcels", where_equals={"pin": "x"})
    assert "pagination:pages=3" in result.transformations


async def test_repeating_a_paged_query_returns_the_same_answer():
    """The paging walk used to extend the list held inside the cached
    page-one payload, and TTLCache hands out its stored dict by reference.
    A repeat resumed from the accumulated length: four identical calls
    returned 250, 450, 650, then 850 records."""
    svc = _PagingService(total=10_000)
    adapter = _paging_adapter(svc)          # one adapter, one cache
    manifest = _real_manifest()
    counts = []
    for _ in range(4):
        result = await adapter.query(manifest, "parcels",
                                     where_equals={"pin": "x"})
        counts.append(len(result.records))
    assert counts == [MAX_QUERY_PAGES * 50] * 4, counts


async def test_sample_mode_stays_capped_and_does_not_page():
    """`sources sample` asks for a tiny bounded read to record a fixture.
    Any layer bigger than the sample sets exceededTransferLimit on the
    first response, so paging would fetch five pages of a thing the caller
    explicitly capped."""
    svc = _PagingService(total=10_000)
    result = await _paging_adapter(svc).query(
        _real_manifest(), "parcels", sample_rows=5)
    assert len(result.records) == 5
    assert len(svc.offsets) == 1, "sample mode paged anyway"


async def test_a_layer_that_ignores_result_offset_does_not_duplicate_rows():
    """A layer can advertise supportsPagination and still ignore
    resultOffset, returning page one again. That batch is non-empty, so the
    empty-batch check cannot see it; the first-record comparison can."""
    svc = _PagingService(total=10_000)
    svc.honours_offset = False
    result = await _paging_adapter(svc).query(
        _real_manifest(), "parcels", where_equals={"pin": "x"})
    ids = [r.canonical.get("pin") for r in result.records]
    assert len(ids) == len(set(ids)), "returned duplicate rows"
    assert len(result.records) == 50
