"""ArcGIS GeocodeServer adapter: a typed address string in, candidate
points out (GitHub issue #3).

Deliberately not a layer on `adapters/arcgis.py`. A `GeocodeServer`'s
`findAddressCandidates` is a different request and a different response
from a `FeatureServer` `query`: no `features`, no `attributes`/`geometry`
split, a `candidates` array with a per-candidate `score`, and a
service-level `spatialReference` rather than a per-feature one. Bolting it
onto a params model built around layers and field mappings would describe
a locator as something it is not.

What this adapter does NOT do is decide a jurisdiction. A geocode is a
coordinate and a confidence, and the jurisdiction comes from running that
coordinate through the same point-in-polygon path everything else uses.
The locator's own `City` and `Subregion` attributes are returned as data
and never read as the answer: `City` is a POSTAL city (a Fairfax County
address reads "ALEXANDRIA"), and `Subregion` is inconsistent across the
locator's own elements — observed live 2026-08-29 returning the FIPS code
"51059" from the road-centerline element and the name "Fairfax County"
from the address-point element for the same query.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..core.errors import InvalidQuery, SourceUnavailable
from ..core.registry import SourceManifest, register_adapter_params
from .base import (Fetcher, HttpFetcher, TTLCache, egress_policy_for,
                   log_source_call, shared_cache)


class ArcGISGeocodeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_url: str
    # Below this the locator's answer is offered as a candidate to choose
    # between rather than used. The number is Commonwealth's, not the
    # publisher's: Esri documents `score` as a 0-100 match quality and
    # states no threshold, so declaring one here (and in the manifest) is
    # the only way a reader can see where the line was drawn.
    min_score: float = 90.0
    # How many the locator may return. The 25-record inline cap applies to
    # candidate lists the same way it applies to feature lists.
    max_locations: int = 10


register_adapter_params("arcgis_geocode", ArcGISGeocodeParams)


@dataclass
class GeocodeCandidate:
    address: str
    lon: float
    lat: float
    score: float
    # The locator element that produced the match ("AddressPoint",
    # "RoadCenterline", "ZipCode", ...). A ZIP-code match is a very
    # different kind of answer from a rooftop one and the caller has to be
    # able to tell them apart.
    matched_by: str
    address_type: str
    postal_city: str
    postal_code: str
    # The WHOLE candidate object, not just its `attributes`. A locator
    # puts the facts that matter most — `location`, `score`, `address` —
    # at the top level, and those coordinates are what the jurisdiction
    # answer is computed from. Hashing only `attributes` meant a response
    # whose coordinates or confidence had changed could carry the same
    # evidence payload hash, which is the one thing the hash exists to
    # make impossible.
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def record_id(self) -> str:
        return "candidate:" + hashlib.sha256(
            f"{self.address}|{self.lon}|{self.lat}".encode()).hexdigest()[:16]

    def canonical(self) -> dict[str, Any]:
        return {"matched_address": self.address,
                "lon": self.lon, "lat": self.lat, "score": self.score,
                "matched_by": self.matched_by,
                "address_type": self.address_type,
                "postal_city": self.postal_city,
                "postal_code": self.postal_code}


@dataclass
class GeocodeResult:
    candidates: list[GeocodeCandidate]
    retrieved_at: str
    cache_age_seconds: int
    from_cache: bool
    transformations: list[str]
    request_url: str
    min_score: float

    def confident(self) -> list[GeocodeCandidate]:
        return [c for c in self.candidates if c.score >= self.min_score]

    def payload_hash(self) -> str:
        raw = json.dumps([c.raw for c in self.candidates], sort_keys=True,
                         separators=(",", ":"), default=str)
        return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _params_of(manifest: SourceManifest) -> ArcGISGeocodeParams:
    return ArcGISGeocodeParams.model_validate(
        manifest.adapter.model_dump(exclude={"type"}))


class ArcGISGeocodeAdapter:
    version = "0.1.0"

    def __init__(self, fetcher: Fetcher | None = None,
                 cache: TTLCache | None = None) -> None:
        self._fetcher = fetcher
        self._cache = cache or shared_cache()

    def _fetcher_for(self, manifest: SourceManifest,
                     service_url: str) -> Fetcher:
        if self._fetcher is not None:
            return self._fetcher
        # Same policy path as every other adapter: the host allowlist comes
        # from this manifest's own service_url and nothing else.
        return HttpFetcher(policy=egress_policy_for(manifest, service_url))

    async def geocode(self, manifest: SourceManifest,
                      single_line: str) -> GeocodeResult:
        text = single_line.strip()
        if not text:
            raise InvalidQuery("geocode needs a non-empty address string")
        p = _params_of(manifest)
        url = f"{p.service_url}/findAddressCandidates"
        params: dict[str, Any] = {
            "f": "json",
            "SingleLine": text,
            "outFields": "*",
            "outSR": "4326",
            "maxLocations": p.max_locations,
        }
        ttl = manifest.freshness.ttl_hint_seconds
        cached = self._cache.get(manifest.id, url, params, ttl)
        if cached is not None:
            result = cached
        else:
            payload = await self._fetcher_for(manifest, p.service_url) \
                .fetch_json(url, params)
            err = payload.get("error")
            if err:
                raise SourceUnavailable(
                    f"geocoder error from {manifest.id}: "
                    f"{err.get('message', 'unknown')} "
                    f"(code {err.get('code')}). Treat as an outage, not "
                    "an address that does not exist.")
            if "candidates" not in payload:
                raise SourceUnavailable(
                    f"geocoder response from {manifest.id} has no "
                    "`candidates` key — the service schema changed or the "
                    "endpoint moved")
            result = self._cache.put(manifest.id, url, params, payload)

        candidates = []
        for cand in result.payload.get("candidates") or []:
            loc = cand.get("location") or {}
            attrs = cand.get("attributes") or {}
            if loc.get("x") is None or loc.get("y") is None:
                continue
            candidates.append(GeocodeCandidate(
                address=cand.get("address") or "",
                lon=float(loc["x"]), lat=float(loc["y"]),
                score=float(cand.get("score") or 0.0),
                matched_by=str(attrs.get("Loc_name") or ""),
                address_type=str(attrs.get("Addr_type") or ""),
                postal_city=str(attrs.get("City") or ""),
                postal_code=str(attrs.get("Postal") or ""),
                raw=cand))
        # The publisher's own ranking, preserved. Sorting by score here
        # would silently reorder ties the locator's element hierarchy
        # already resolved (address points before centerlines before ZIP
        # codes), and that hierarchy is the publisher's judgment.
        log_source_call(manifest, "findAddressCandidates",
                        {"SingleLine": text}, len(candidates))
        return GeocodeResult(
            candidates=candidates, retrieved_at=result.retrieved_at,
            cache_age_seconds=result.cache_age_seconds,
            from_cache=result.from_cache,
            transformations=["geocode:findAddressCandidates",
                             "crs:source->EPSG4326"],
            request_url=result.request_url, min_score=p.min_score)

    async def health(self, manifest: SourceManifest) -> dict[str, Any]:
        """The probe is a known address the locator must still find. A
        locator that answers HTTP 200 with zero candidates for everything
        is broken in exactly the way a reachability check cannot see."""
        known = manifest.health.expect.get("known_address")
        if not known:
            raise InvalidQuery(
                f"{manifest.id} declares no health.expect.known_address")
        floor = float(manifest.health.expect.get("min_score",
                                                 _params_of(manifest).min_score))
        result = await self.geocode(manifest, known)
        best = max((c.score for c in result.candidates), default=0.0)
        return {"probe": "geocode_known_address", "address": known,
                "candidates": len(result.candidates), "best_score": best,
                "min_score": floor, "healthy": best >= floor}
