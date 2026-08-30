"""ArcGIS REST adapter (design/adapters.md § 2-3).

Covers FeatureServer/MapServer layer info and queries. The platform's known
quirks are handled by name: HTTP-200-with-error-body responses raise typed
errors (a recorded fixture proves it), `exceededTransferLimit` becomes an explicit
truncated-pagination state, and `editingInfo.lastEditDate` feeds `source_updated_at`
when present — null with a warning when the layer doesn't publish one, never
a guess.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.errors import InvalidQuery, SourceUnavailable
from ..core.registry import (DataClassification, SourceManifest,
                             register_adapter_params)
from .base import (FetchResult, Fetcher, HttpFetcher, TTLCache, log,
                   egress_policy_for, log_source_call, shared_cache)


class LayerDecl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer_id: int
    field_mapping: dict[str, str]  # canonical -> source field
    geometry: str                  # polygon | point | line | none
    id_field: str                  # the source's stable record-id field
    # Real publishers sometimes split layers across separate FeatureServers
    # (e.g. Richmond City: Parcels and ZoningDistricts are two services on
    # the same host, not two layers of one service like Fairfax). Most
    # manifests omit this and every layer shares the top-level service_url.
    # The egress policy is still derived from the top-level service_url
    # (host-allowlist only), so an override must resolve to the same host —
    # a genuinely cross-host split needs a manifest-level egress change too,
    # not just this field.
    service_url: str | None = None


class ArcGISParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_url: str
    layers: dict[str, LayerDecl]
    field_mapping_version: str = "1"

    @model_validator(mode="after")
    def _layer_overrides_stay_on_host(self) -> "ArcGISParams":
        # The egress policy's host allowlist is derived from the top-level
        # service_url only (base.egress_policy_for); a layer override to a
        # different host would be refused live (fail-closed), but only at
        # request time. Catch it here so a broken manifest fails validation,
        # not the first real query.
        top_host = urlparse(self.service_url).hostname
        for key, layer in self.layers.items():
            if layer.service_url is None:
                continue
            layer_host = urlparse(layer.service_url).hostname
            if layer_host != top_host:
                raise ValueError(
                    f"layer {key!r} service_url host {layer_host!r} does "
                    f"not match the manifest's top-level host {top_host!r} "
                    "— the egress policy is derived from the top-level "
                    "service_url only, so a genuinely cross-host layer "
                    "needs a manifest-level egress change, not just this "
                    "override")
        return self


register_adapter_params("arcgis", ArcGISParams)


@dataclass
class ArcGISRecord:
    canonical: dict[str, Any]
    record_id: str
    raw: dict[str, Any]
    geometry: dict | None
    # The platform's own `returnCentroid` point, when asked for. It is a
    # LABEL point (centre of mass), not a guaranteed interior point: a
    # Virginia county that encloses an independent city is a topological
    # donut and its centroid lands in the city. Never use it to decide
    # containment (docs/audits/centroid-property-2026-08-28.json).
    centroid: dict | None = None


@dataclass
class ArcGISQueryResult:
    records: list[ArcGISRecord]
    retrieved_at: str
    cache_age_seconds: int
    source_updated_at: str | None
    exceeded_transfer_limit: bool
    transformations: list[str]
    request_url: str
    from_cache: bool = False

    def payload_hash(self) -> str:
        raw = json.dumps([r.raw for r in self.records], sort_keys=True,
                         separators=(",", ":"), default=str)
        return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _params_of(manifest: SourceManifest) -> ArcGISParams:
    return ArcGISParams.model_validate(
        manifest.adapter.model_dump(exclude={"type"}))


def _layer_root(p: ArcGISParams, layer: LayerDecl) -> str:
    return layer.service_url or p.service_url


def _apply_exposure_allowlist(manifest: SourceManifest, payload: dict,
                              layer: LayerDecl | None) -> dict:
    """../../../design/architecture.md decision 0014 § 3: for a `sensitive_public` source, `exposure_
    allowlist` is a field-level gate on what may ever leave this function —
    not just a manifest-schema requirement that the source has one.
    Filtering here, before the response reaches the cache, means a
    non-allowlisted field can never be cached, mapped into a canonical
    record, or exposed via `raw_recovery`. The layer's own id_field is
    always retained: it is an internal record identifier, not a data
    field the allowlist is meant to gate."""
    if manifest.access.data_classification != DataClassification.sensitive_public:
        return payload
    features = payload.get("features")
    if not isinstance(features, list):
        return payload
    allowed = set(manifest.access.exposure_allowlist or [])
    if layer is not None:
        allowed = allowed | {layer.id_field}
    filtered = []
    for feat in features:
        if not isinstance(feat, dict) or not isinstance(
                feat.get("attributes"), dict):
            filtered.append(feat)
            continue
        kept = {k: v for k, v in feat["attributes"].items() if k in allowed}
        filtered.append({**feat, "attributes": kept})
    return {**payload, "features": filtered}


def _raise_on_error_body(payload: dict, host_desc: str) -> None:
    """ArcGIS returns HTTP 200 with an `error` object for most failures."""
    err = payload.get("error")
    if not err:
        return
    code = err.get("code")
    message = err.get("message", "unknown ArcGIS error")
    if code in (400, 498, 499) or "Invalid" in str(message):
        raise InvalidQuery(
            f"ArcGIS rejected the query against {host_desc}: "
            f"{message} (code {code}). Check field names and geometry.")
    raise SourceUnavailable(
        f"ArcGIS error from {host_desc}: {message} (code {code}). "
        "Treat as an outage, not an empty result.")


def _epoch_ms_to_iso(ms: int | None) -> str | None:
    if not ms:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _first_record_id(features: list[dict]) -> object:
    """Identity of a page's first row, for spotting a repeated page.

    Returns None for an empty list, which never equals a real page's
    identity, so an empty batch is not mistaken for a repeat.
    """
    if not features:
        return None
    attrs = features[0].get("attributes") or {}
    return tuple(sorted(attrs.items(), key=lambda kv: kv[0])) or None


# Each extra page is another request to a government service, so the
# walk is bounded rather than open-ended. Five pages at the default
# record count covers every query this project issues today; past that
# the answer is reported as truncated, which is what the caller got
# before pagination existed at all.
MAX_QUERY_PAGES = 5


class ArcGISAdapter:
    version = "0.1.0"

    def __init__(self, fetcher: Fetcher | None = None,
                 cache: TTLCache | None = None) -> None:
        self._fetcher = fetcher
        self._cache = cache or shared_cache()

    def _fetcher_for(self, manifest: SourceManifest,
                     service_url: str) -> Fetcher:
        if self._fetcher is not None:
            return self._fetcher
        return HttpFetcher(policy=egress_policy_for(manifest, service_url))

    async def _get(self, manifest: SourceManifest, url: str,
                   params: dict[str, Any], *,
                   layer: LayerDecl | None = None) -> FetchResult:
        ttl = manifest.freshness.ttl_hint_seconds
        cached = self._cache.get(manifest.id, url, params, ttl)
        if cached is not None:
            return cached
        fetcher = self._fetcher_for(manifest,
                                    _params_of(manifest).service_url)
        payload = await fetcher.fetch_json(url, params)
        _raise_on_error_body(payload, manifest.id)
        payload = _apply_exposure_allowlist(manifest, payload, layer)
        return self._cache.put(manifest.id, url, params, payload)

    async def layer_info(self, manifest: SourceManifest,
                         layer_key: str) -> dict:
        p = _params_of(manifest)
        layer = self._layer(p, layer_key, manifest)
        url = f"{_layer_root(p, layer)}/{layer.layer_id}"
        result = await self._get(manifest, url, {"f": "json"})
        log_source_call(manifest, f"layer_info:{layer_key}", {}, None)
        return result.payload

    async def query(self, manifest: SourceManifest, layer_key: str, *,
                    where_equals: dict[str, str] | None = None,
                    object_ids: list[int] | None = None,
                    geometry_point: tuple[float, float] | None = None,
                    intersect_geometry: dict | None = None,
                    distance_meters: float | None = None,
                    return_geometry: bool = False,
                    return_centroid: bool = False,
                    simplify_tolerance: float | None = None,
                    record_count: int = 50,
                    sample_rows: int | None = None) -> ArcGISQueryResult:
        """`where_equals` takes CANONICAL field names (the manifest's
        field_mapping keys) — callers never speak vendor field names
        (../../../design/architecture.md § 27). Values are escaped and matched exactly.

        `simplify_tolerance` is degrees of allowable offset, passed to the
        platform's own `maxAllowableOffset` generalization so a polygon
        that would be hundreds of KB fits an inline response. It is a
        lossy transformation of the government's geometry, so it is only
        honoured alongside `return_geometry` and is recorded in
        `transformations` — a caller reading the envelope can always see
        that the vertices are not the source's own."""
        p = _params_of(manifest)
        layer = self._layer(p, layer_key, manifest)
        url = f"{_layer_root(p, layer)}/{layer.layer_id}/query"

        params: dict[str, Any] = {
            "f": "json",
            "outFields": ",".join(sorted(set(layer.field_mapping.values())
                                         | {layer.id_field})),
            "resultRecordCount": record_count,
            "returnGeometry": "true" if return_geometry else "false",
        }
        transformations = [f"field_mapping:v{p.field_mapping_version}"]
        clauses = 0
        if where_equals is not None:
            parts = []
            for canon, value in sorted(where_equals.items()):
                src_field = layer.field_mapping.get(canon)
                if src_field is None:
                    raise InvalidQuery(
                        f"field {canon!r} is not mapped on layer "
                        f"{layer_key!r} of {manifest.id}; mapped: "
                        f"{sorted(layer.field_mapping)}")
                escaped = str(value).replace("'", "''")
                parts.append(f"{src_field} = '{escaped}'")
            params["where"] = " AND ".join(parts)
            clauses += 1
        if object_ids is not None:
            params["objectIds"] = ",".join(str(i) for i in object_ids)
            clauses += 1
        if geometry_point is not None:
            lon, lat = geometry_point
            params.update({
                "geometry": json.dumps({"x": lon, "y": lat,
                                        "spatialReference": {"wkid": 4326}}),
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            })
            clauses += 1
        if intersect_geometry is not None:
            params.update({
                "geometry": json.dumps(intersect_geometry),
                "geometryType": "esriGeometryPolygon",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            })
            clauses += 1
        if distance_meters is not None:
            if geometry_point is None and intersect_geometry is None:
                raise InvalidQuery(
                    "distance_meters buffers a geometry filter; pass "
                    "geometry_point or intersect_geometry with it")
            # Server-side buffering runs against the layer's TRUE geometry,
            # not the generalized geometry `simplify_tolerance` returns, so
            # a proximity answer is not degraded by the display shortcut.
            params["distance"] = distance_meters
            params["units"] = "esriSRUnit_Meter"
            transformations.append(f"proximity_buffer:{distance_meters}m")
        if sample_rows is not None:
            # Contributor-workflow escape: a tiny bounded sample for fixture
            # recording (`commonwealth sources sample`). Hard-capped.
            params["where"] = "1=1"
            params["resultRecordCount"] = min(sample_rows, 5)
            clauses += 1
        if clauses == 0:
            raise InvalidQuery("refusing an unbounded ArcGIS query: pass "
                               "field filters, object ids, or geometry")
        if return_centroid:
            params["returnCentroid"] = "true"
        if return_geometry or return_centroid:
            params["outSR"] = "4326"
            transformations.append("crs:source->EPSG4326")
        if return_geometry:
            if simplify_tolerance is not None:
                params["maxAllowableOffset"] = simplify_tolerance
                transformations.append(
                    f"geometry_simplified:maxAllowableOffset="
                    f"{simplify_tolerance}deg")
        elif simplify_tolerance is not None:
            raise InvalidQuery(
                "simplify_tolerance only applies when return_geometry is "
                "set; refusing to silently ignore it")

        result = await self._get(manifest, url, params, layer=layer)
        payload = result.payload

        features = payload.get("features")
        if features is None:
            raise SourceUnavailable(
                f"ArcGIS response from {manifest.id} has no `features` key — "
                "the service schema changed or the endpoint moved")

        # The service caps how many rows one response may carry and sets
        # exceededTransferLimit when it did. Reporting that is honest but
        # still leaves the caller with a partial answer, so follow the
        # pages — bounded, because each one is another request to a
        # government service and the politeness budget is real.
        pages_read = 1
        more_remains = bool(payload.get("exceededTransferLimit"))
        # `features` is the list inside the cached page-one payload, and
        # TTLCache hands out its stored dict by reference. Extending it in
        # place rewrote that cache entry, so a repeat of the same query
        # resumed from the accumulated length and grew without bound
        # (measured: 250, 450, 650, 850 records on four identical calls).
        # The walk builds its own list.
        features = list(features)
        # `sample_rows` is a deliberately tiny bounded read for fixture
        # recording. Any layer with more rows than the sample sets
        # exceededTransferLimit on the first response, so paging here would
        # fetch five pages of a thing the caller asked to cap at five rows.
        # layer_info is a second request, so it is fetched only once
        # there is actually a second page to consider. A query that fails
        # on a missing `features` key above never pays for it.
        may_page = more_remains and sample_rows is None
        info = await self.layer_info(manifest, layer_key)
        if may_page:
            may_page = bool((info.get("advancedQueryCapabilities") or {})
                            .get("supportsPagination"))
        while more_remains and may_page and pages_read < MAX_QUERY_PAGES:
            page_params = dict(params)
            page_params["resultOffset"] = len(features)
            page = await self._get(manifest, url, page_params, layer=layer)
            batch = page.payload.get("features")
            if not batch:
                more_remains = False
                break
            # A layer can advertise supportsPagination and still ignore
            # resultOffset, which returns page one again — non-empty, so
            # the check above cannot see it. Compare the first record
            # instead: observed behaviour rather than an advertised claim.
            if _first_record_id(batch) == _first_record_id(features):
                log.warning("%s ignored resultOffset on layer %s; stopped "
                            "the page walk to avoid duplicate rows",
                            manifest.id, layer_key)
                break
            features.extend(batch)
            pages_read += 1
            more_remains = bool(page.payload.get("exceededTransferLimit"))
        if pages_read > 1:
            transformations.append(f"pagination:pages={pages_read}")

        records = []
        for feat in features:
            attrs = feat.get("attributes", {})
            canonical = {canon: attrs.get(src)
                         for canon, src in layer.field_mapping.items()}
            rid = attrs.get(layer.id_field)
            records.append(ArcGISRecord(
                canonical=canonical,
                record_id=f"{layer.id_field}:{rid}",
                raw=attrs,
                geometry=feat.get("geometry"),
                centroid=feat.get("centroid")))

        updated = _epoch_ms_to_iso(
            (info.get("editingInfo") or {}).get("lastEditDate"))

        log_source_call(manifest, f"query:{layer_key}",
                        params, len(records))
        return ArcGISQueryResult(
            records=records,
            retrieved_at=result.retrieved_at,
            cache_age_seconds=result.cache_age_seconds,
            from_cache=result.from_cache,
            source_updated_at=updated,
            # True only when rows remain AFTER the page budget ran out,
            # so a result that paged to completion is not called partial.
            exceeded_transfer_limit=more_remains,
            transformations=transformations,
            request_url=result.request_url)

    async def health(self, manifest: SourceManifest,
                     layer_key: str) -> dict[str, Any]:
        p = _params_of(manifest)
        layer = self._layer(p, layer_key, manifest)
        url = f"{_layer_root(p, layer)}/{layer.layer_id}/query"
        result = await self._get(manifest, url, {
            "f": "json", "where": "1=1", "returnCountOnly": "true"})
        count = result.payload.get("count")
        raw_min = manifest.health.expect.get("min_features", 1)
        expect_min = int(raw_min.get(layer_key, 1)
                         if isinstance(raw_min, dict) else raw_min)
        healthy = isinstance(count, int) and count >= expect_min
        return {"layer": layer_key, "feature_count": count,
                "min_expected": expect_min, "healthy": healthy}

    @staticmethod
    def _layer(p: ArcGISParams, layer_key: str,
               manifest: SourceManifest) -> LayerDecl:
        layer = p.layers.get(layer_key)
        if layer is None:
            raise InvalidQuery(
                f"manifest {manifest.id} declares no layer {layer_key!r}; "
                f"declared: {sorted(p.layers)}")
        return layer

    def mapped_canonical_fields(self, manifest: SourceManifest,
                                layer_key: str) -> frozenset[str]:
        """The canonical field names a layer's field_mapping declares —
        callers use this to check whether an optional scoping filter (e.g.
        `fips`) is available before adding it to `where_equals`, without
        reaching into ArcGIS-specific structure themselves."""
        p = _params_of(manifest)
        layer = self._layer(p, layer_key, manifest)
        return frozenset(layer.field_mapping)
