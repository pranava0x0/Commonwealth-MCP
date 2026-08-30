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


class JurisdictionScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str
    fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _known_mode(self) -> "JurisdictionScope":
        known = {"fips", "fips_any_of", "jurisdiction_names", "none"}
        if self.mode not in known:
            raise ValueError(f"jurisdiction_scope.mode must be one of "
                             f"{sorted(known)}, got {self.mode!r}")
        if self.mode != "none" and not self.fields:
            raise ValueError(f"jurisdiction_scope mode {self.mode!r} needs "
                             "at least one field")
        return self


class LayerDecl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer_id: int
    field_mapping: dict[str, str]  # canonical -> source field
    geometry: str                  # polygon | point | line | none
    id_field: str                  # the source's stable record-id field
    # Canonical names whose source column is numeric. ArcGIS rejects
    # `NUMERIC_COL = '51059'` with a bare "Unable to complete operation",
    # and a caller passing a FIPS or ZIP as the string it is spelled as
    # has no way to know which layers store it as a number — VGIN's
    # address points store ZIP_5 as an integer, its landmarks store
    # FIPScode as one, and its parcels store FIPS as text. Declaring it
    # here keeps that in the manifest, where the layer's schema belongs.
    numeric_fields: list[str] = Field(default_factory=list)
    # The publisher's OWN coded-value domains, copied from the layer
    # metadata, canonical field -> {code: label}. Decoding is only ever
    # done from a list a publisher published; there is no inferring what
    # a code might mean.
    value_labels: dict[str, dict[str, str]] = Field(default_factory=dict)
    # How a query against this layer is narrowed to one jurisdiction.
    # Left unset, the tools fall back to a single mapped `fips` field,
    # which is what every layer registered before roads needed. Roads
    # broke that twice over: VGIN's centerlines carry FIPS_L and FIPS_R
    # for the two sides of a segment, so "in this locality" is genuinely
    # a disjunction; and VDOT's route master keys on its own jurisdiction
    # NAMES ("Fairfax County", "Town of Vienna") under a code column that
    # is VDOT's numbering rather than FIPS. Both live here so the
    # knowledge stays in the manifest.
    #   mode: fips | fips_any_of | jurisdiction_names | none
    #   fields: canonical field names the mode applies to
    jurisdiction_scope: JurisdictionScope | None = None
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
                    where_equals: dict[str, str | int | float] | None = None,
                    where_prefix: dict[str, str] | None = None,
                    where_any_of: list[dict[str, str | int | float]] | None = None,
                    object_ids: list[int] | None = None,
                    geometry_point: tuple[float, float] | None = None,
                    intersect_geometry: dict | None = None,
                    distance_meters: float | None = None,
                    return_geometry: bool = False,
                    return_centroid: bool = False,
                    simplify_tolerance: float | None = None,
                    distinct_fields: list[str] | None = None,
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
        if layer.value_labels:
            transformations.append(
                "value_labels:" + ",".join(sorted(layer.value_labels)))
        clauses = 0

        def src_field_of(canon: str) -> str:
            field = layer.field_mapping.get(canon)
            if field is None:
                raise InvalidQuery(
                    f"field {canon!r} is not mapped on layer "
                    f"{layer_key!r} of {manifest.id}; mapped: "
                    f"{sorted(layer.field_mapping)}")
            return field

        def literal(canon: str, value: object) -> str:
            """A quoted string, or a bare number for a numeric column.

            ArcGIS rejects `NUMERIC_COL = '24450'` with a bare "Unable to
            complete operation" (HTTP 200, error 400) — VGIN's address
            points store ZIP_5 as an integer and its landmarks store
            FIPScode as one, while its parcels store FIPS as text. Which
            is which comes from the manifest's `numeric_fields`, so a
            caller passing "51059" does not have to know; a real Python
            int or float is also taken at its word."""
            numeric = canon in layer.numeric_fields
            if not numeric and (isinstance(value, bool)
                                or not isinstance(value, (int, float))):
                return "'" + str(value).replace("'", "''") + "'"
            if numeric and not isinstance(value, (int, float)):
                try:
                    value = float(value) if "." in str(value) else int(value)
                except ValueError:
                    raise InvalidQuery(
                        f"{canon!r} is declared numeric on layer "
                        f"{layer_key!r} of {manifest.id} and {value!r} is "
                        "not a number") from None
            return repr(value)

        where_parts: list[str] = []
        if where_equals is not None:
            for canon, value in sorted(where_equals.items()):
                where_parts.append(
                    f"{src_field_of(canon)} = {literal(canon, value)}")
        if where_prefix is not None:
            for canon, value in sorted(where_prefix.items()):
                # LIKE 'x%' is a prefix match, not a fuzzy one, and the
                # tool descriptions say so. `%` and `_` are LIKE's own
                # wildcards, so a caller's literal ones are escaped to
                # stop "50% Grade Rd" matching everything.
                escaped = (str(value).replace("'", "''")
                           .replace("\\", "\\\\")
                           .replace("%", "\\%").replace("_", "\\_"))
                where_parts.append(
                    f"{src_field_of(canon)} LIKE '{escaped}%' ESCAPE '\\'")
        if where_any_of:
            # A disjunction ANDed with the rest. Real layers split one
            # concept across several fields — VGIN's road centerlines
            # carry FIPS_L and FIPS_R for the two sides of a segment, so
            # "in this locality" is genuinely an OR and an AND of
            # equalities cannot express it.
            groups = []
            for group in where_any_of:
                terms = [f"{src_field_of(c)} = {literal(c, v)}"
                         for c, v in sorted(group.items())]
                if terms:
                    groups.append("(" + " AND ".join(terms) + ")")
            if groups:
                where_parts.append("(" + " OR ".join(groups) + ")")
        if where_parts:
            params["where"] = " AND ".join(where_parts)
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
        if distinct_fields is not None:
            # The platform's own DISTINCT. It answers "which localities
            # does this ZIP touch" in one request instead of paging every
            # address point in the ZIP and de-duplicating here — which for
            # a dense ZIP would be tens of thousands of rows to learn
            # three values.
            if return_geometry or return_centroid:
                raise InvalidQuery(
                    "distinct_fields returns attribute tuples, not "
                    "features; it cannot be combined with geometry")
            params["outFields"] = ",".join(
                src_field_of(c) for c in distinct_fields)
            params["returnDistinctValues"] = "true"
            # Observed on VGIN's address points, 2026-08-29: the same
            # distinct query succeeds without `resultRecordCount` and
            # fails with it, HTTP 200 carrying error 400 "Unable to
            # complete operation". So the row cap comes off, and the only
            # thing keeping the answer bounded is that a distinct query
            # must be over a low-cardinality field — locality codes, not
            # address ids. The egress byte cap is the backstop.
            params.pop("resultRecordCount", None)
            transformations.append(
                "distinct:" + ",".join(sorted(distinct_fields)))
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
        # Provenance is per page. Page one can come from cache while a
        # later page is fetched live (an earlier walk cached page one and
        # then failed, or the pages straddle the TTL), and reporting only
        # page one's would label later-page evidence with the wrong access
        # path and retrieval time.
        page_results = [result]
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
            page_results.append(page)
            pages_read += 1
            more_remains = bool(page.payload.get("exceededTransferLimit"))
        if pages_read > 1:
            transformations.append(f"pagination:pages={pages_read}")

        records = []
        for feat in features:
            attrs = feat.get("attributes", {})
            if distinct_fields is not None:
                # A distinct row is a tuple of values, not a feature: the
                # id_field is not in the response and there is no single
                # record it came from. Naming it OBJECTID:None would
                # invent a record that does not exist, so the identity is
                # the tuple itself.
                canonical = {canon: attrs.get(src_field_of(canon))
                             for canon in distinct_fields}
                rid = "|".join(f"{c}={canonical[c]}"
                               for c in sorted(distinct_fields))
                records.append(ArcGISRecord(
                    canonical=canonical, record_id=f"distinct:{rid}",
                    raw=attrs, geometry=None))
                continue
            canonical = {canon: attrs.get(src)
                         for canon, src in layer.field_mapping.items()}
            for canon, labels in layer.value_labels.items():
                raw_code = canonical.get(canon)
                # The raw code stays. A label is the publisher's word for
                # a code, and a caller checking against the publisher's
                # own documentation needs the code it documents. The key
                # is always present so the record shape does not change
                # with the data: null means the publisher has no code, or
                # has one this manifest's copy of its list does not
                # cover. Neither is a reason to guess a label.
                canonical[f"{canon}_label"] = (
                    None if raw_code is None else labels.get(str(raw_code)))
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
        # Report the weakest link across the pages. Claiming the freshest
        # page's numbers for the whole set would overstate how current the
        # answer is, which is the one thing this envelope exists not to do.
        return ArcGISQueryResult(
            records=records,
            retrieved_at=min(r.retrieved_at for r in page_results),
            cache_age_seconds=max(r.cache_age_seconds for r in page_results),
            from_cache=any(r.from_cache for r in page_results),
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

    def layer_keys(self, manifest: SourceManifest) -> frozenset[str]:
        """The layer keys a manifest declares, so a tool can choose among
        them without reaching into ArcGIS-specific structure."""
        return frozenset(_params_of(manifest).layers)

    def jurisdiction_scope(self, manifest: SourceManifest,
                           layer_key: str) -> "JurisdictionScope | None":
        """A layer's own declaration of how it is narrowed to one
        jurisdiction. Callers read this rather than reaching into
        ArcGIS-specific structure themselves."""
        p = _params_of(manifest)
        return self._layer(p, layer_key, manifest).jurisdiction_scope

    def mapped_canonical_fields(self, manifest: SourceManifest,
                                layer_key: str) -> frozenset[str]:
        """The canonical field names a layer's field_mapping declares —
        callers use this to check whether an optional scoping filter (e.g.
        `fips`) is available before adding it to `where_equals`, without
        reaching into ArcGIS-specific structure themselves."""
        p = _params_of(manifest)
        layer = self._layer(p, layer_key, manifest)
        return frozenset(layer.field_mapping)
