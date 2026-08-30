"""Geo tools: find_parcel and find_zoning (design/domain-servers.md § 3).

Selection discipline is ../../../design/architecture.md decision 0005 as Chosen: up to the top two
selectable sources are queried and every per-source result is surfaced;
nothing reconciles two official answers into one. Ambiguous jurisdictions
return candidates with requires_user_choice (../../../design/architecture.md decision 0004). Registry gaps,
outages, and empty results are three different coverage shapes, never one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..adapters.arcgis import ArcGISQueryResult
from ..adapters.arcgis_geocode import GeocodeResult
from ..core.assemble import (EnvelopeBuilder, failure, result_dim,
                             selection_coverage)
from ..core.envelope import (AccessPath, Coverage, Envelope,
                             ExecutionCoverage, PaginationCoverage,
                             RegistryCoverage, ResultCoverage, WarningCode)
from ..core.errors import CommonwealthError, InvalidQuery
from ..core.jurisdiction import Jurisdiction, JurisdictionKind
from ..core.registry import SourceManifest
from ..core.toolreg import ToolRegistry, ToolSpec
from ..runtime import RuntimeContext
from .containment import resolve_point, warn_if_near_a_border

GEO_TOOLS = ToolRegistry(package="geo")

INLINE_RECORD_CAP = 25

# Degrees of allowable offset handed to the platform's own generalization.
# ~0.0002 deg is roughly 22 m at Virginia's latitude: enough to shrink a
# county polygon from ~679 KB / 16,641 vertices to ~11 KB / 523 and still
# draw the right shape. It is lossy, so it is declared in the record, in
# `transformations`, and in a boundary_precision warning — never silently.
BOUNDARY_SIMPLIFY_DEGREES = 0.0002

# How far from a coordinate an address point may sit and still be
# "at" it. Address points are placed on structures, so a point taken
# from a map click or a parcel centroid is routinely tens of metres
# from the rooftop it belongs to; an exact intersect would answer
# "no address here" for a house.
ADDRESS_POINT_RADIUS_M = 100.0

# Which boundary layer answers for which kind of jurisdiction. Virginia's
# independent cities live in the SAME layer as counties, not inside them,
# which is the whole reason this table is explicit rather than inferred.
BOUNDARY_LAYER_FOR_KIND = {
    JurisdictionKind.county: "localities",
    JurisdictionKind.independent_city: "localities",
    JurisdictionKind.town: "towns",
}


def _builder(ctx: RuntimeContext, tool: str) -> EnvelopeBuilder:
    return EnvelopeBuilder(server=ctx.server_name,
                           server_version=ctx.server_version, tool=tool,
                           contract_version="1",
                           registry_revision=ctx.sources.revision,
                           adapters=ctx.adapters)


@dataclass
class _Frame:
    """Resolved jurisdiction stack, or the envelope that ends the call."""

    stack: list[str] | None = None
    early: Envelope | None = None


def _resolve_frame(ctx: RuntimeContext, b: EnvelopeBuilder,
                   jurisdiction: str) -> _Frame:
    resolution = ctx.jurisdictions.resolve(jurisdiction)
    if resolution.resolved is not None:
        j = resolution.resolved
        stack = [j.id] + [p.id for p in ctx.jurisdictions.parents_of(j)]
        return _Frame(stack=stack)
    if resolution.candidates:
        env = b.build(
            {"resolved": None,
             "candidates": [c.model_dump() for c in resolution.candidates],
             "note": "The jurisdiction is ambiguous. Present these "
                     "candidates to the user; do not select one yourself."},
            Coverage(registry=RegistryCoverage.covered,
                     execution=ExecutionCoverage.complete,
                     pagination=PaginationCoverage.complete,
                     result=ResultCoverage.hit),
            requires_user_choice=True)
        return _Frame(early=env)
    env = b.build(
        {"results": [],
         "note": f"{jurisdiction!r} matches no Virginia jurisdiction in the "
                 "table. registry.resolve_jurisdiction shows what resolves."},
        Coverage(registry=RegistryCoverage.covered,
                 execution=ExecutionCoverage.complete,
                 pagination=PaginationCoverage.complete,
                 result=ResultCoverage.empty))
    return _Frame(early=env)


def _source_entry(b: EnvelopeBuilder, m: SourceManifest,
                  q: ArcGISQueryResult) -> str:
    return b.add_source(
        source_id=m.id, publisher=m.publisher.agency, system=m.adapter.type,
        dataset=m.name, jurisdiction=m.jurisdiction,
        authority_level=m.publisher.authority_level,
        access_path=AccessPath.cache if q.from_cache else AccessPath.live,
        source_updated_at=q.source_updated_at, retrieved_at=q.retrieved_at,
        cache_age_seconds=q.cache_age_seconds)


def _records_block(b: EnvelopeBuilder, src_ref: str, q: ArcGISQueryResult,
                   m: SourceManifest) -> dict:
    inline = q.records[:INLINE_RECORD_CAP]
    if len(q.records) > len(inline):
        b.warn(WarningCode.truncated_inline,
               f"{len(q.records)} records retrieved; {len(inline)} shown "
               "inline. Narrow the query for the rest.", m.id)
    rows = []
    for r in inline:
        ev = b.add_evidence(source_ref=src_ref, record_id=r.record_id,
                            retrieved_at=q.retrieved_at,
                            transformations=q.transformations,
                            payload_hash=q.payload_hash())
        rows.append({**r.canonical, "record_id": r.record_id,
                     "evidence_ref": ev})
    return {"source_ref": src_ref, "source_id": m.id,
            "records": rows, "record_count": len(q.records)}


def _pagination_dim(results: list[ArcGISQueryResult]) -> PaginationCoverage:
    if not results:
        return PaginationCoverage.unknown
    if any(q.exceeded_transfer_limit for q in results):
        return PaginationCoverage.truncated
    return PaginationCoverage.complete


def _compare(blocks: list[dict], field_name: str) -> dict | None:
    """Cross-source surface (0005-C): when two sources answered, say whether
    they agree on the primary field, and never merge them. A source with no
    matching record is not a disagreement — it has nothing to compare, which
    is a different and accurate shape (e.g. VGIN's statewide data-call lag on a
    parcel the locality's own system already has)."""
    if len(blocks) < 2:
        return None
    sets = [sorted({r.get(field_name) for r in blk["records"]
                    if r.get(field_name) is not None})
            for blk in blocks]
    per_source = [{"source_ref": blk["source_ref"], "values": vals}
                 for blk, vals in zip(blocks, sets)]
    if any(not s for s in sets):
        return {"compared_field": field_name, "agreement": None,
               "per_source": per_source,
               "note": "At least one source returned no matching record; "
                       "there is nothing to compare against the other "
                       "source's answer."}
    agreement = sets[0] == sets[1]
    out = {"compared_field": field_name, "agreement": agreement,
           "per_source": per_source}
    if not agreement:
        out["note"] = ("Official sources disagree; both answers are shown "
                       "and neither has been reconciled away.")
    return out


def _scoped_where(ctx: RuntimeContext, m: SourceManifest, layer_key: str,
                  stack: list[str], where_equals: dict[str, str],
                  ) -> dict[str, str]:
    """A source registered above the specific jurisdiction (e.g. VGIN's
    statewide `jurisdiction: va`, matched via stack inheritance) spans every
    locality's data in one layer. A locality-scoped id like a parcel PIN is
    not guaranteed unique across localities, so an unscoped query can return
    another jurisdiction's record as a false 'hit'. Add a FIPS filter when
    the source is being queried outside its own declared jurisdiction and
    the layer maps a `fips` field; local sources (jurisdiction == stack[0])
    and layers with no `fips` mapping are returned unchanged."""
    if m.jurisdiction == stack[0]:
        return where_equals
    if "fips" not in ctx.arcgis.mapped_canonical_fields(m, layer_key):
        return where_equals
    fips = next((j.fips for jid in stack
                if (j := ctx.jurisdictions.get(jid)) and j.fips), None)
    if fips is None:
        return where_equals
    return {**where_equals, "fips": fips}


async def find_parcel(ctx: RuntimeContext, jurisdiction: str,
                      pin: str = "", lon: float | None = None,
                      lat: float | None = None) -> Envelope:
    b = _builder(ctx, "geo.find_parcel")
    # Half a point first: with only `lon`, the two-input check below
    # sees no point at all and reports "pass exactly one", which is
    # a misdiagnosis of a missing `lat`.
    if (lon is None) != (lat is None):
        raise InvalidQuery("a point needs both lon and lat")
    if bool(pin) == (lon is not None and lat is not None):
        raise InvalidQuery("pass exactly one of `pin` or a lon/lat point")

    frame = _resolve_frame(ctx, b, jurisdiction)
    if frame.early is not None:
        return frame.early
    stack = frame.stack or []

    selected = ctx.sources.select("parcel.lookup", stack)
    registry_dim, gaps = selection_coverage(ctx.sources, "parcel.lookup", stack,
                                             selected)
    blocks: list[dict] = []
    failures = []
    queries: list[ArcGISQueryResult] = []
    for m in selected:
        try:
            if pin:
                where = _scoped_where(ctx, m, "parcels", stack, {"pin": pin})
                q = await ctx.arcgis.query(m, "parcels", where_equals=where)
            else:
                q = await ctx.arcgis.query(m, "parcels",
                                           geometry_point=(lon, lat))
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        queries.append(q)
        blocks.append(_records_block(b, _source_entry(b, m, q), q, m))
    execution = (ExecutionCoverage.complete if not failures
                 else ExecutionCoverage.failed if not blocks
                 else ExecutionCoverage.partial)
    total = sum(blk["record_count"] for blk in blocks)
    data: dict = {"results": blocks}
    comparison = _compare(blocks, "pin")
    if comparison:
        data["comparison"] = comparison
    coverage = Coverage(
        registry=registry_dim, execution=execution,
        pagination=_pagination_dim(queries),
        result=result_dim(total),
        jurisdictions_searched=stack if selected else [],
        jurisdictions_unavailable=gaps,
        source_failures=failures,
        known_limitations=sorted({lim for m in selected
                                  for lim in m.coverage.known_limitations}))
    return b.build(data, coverage)


async def find_zoning(ctx: RuntimeContext, jurisdiction: str,
                      pin: str = "", lon: float | None = None,
                      lat: float | None = None) -> Envelope:
    b = _builder(ctx, "geo.find_zoning")
    # Half a point first: with only `lon`, the two-input check below
    # sees no point at all and reports "pass exactly one", which is
    # a misdiagnosis of a missing `lat`.
    if (lon is None) != (lat is None):
        raise InvalidQuery("a point needs both lon and lat")
    if bool(pin) == (lon is not None and lat is not None):
        raise InvalidQuery("pass exactly one of `pin` or a lon/lat point")

    frame = _resolve_frame(ctx, b, jurisdiction)
    if frame.early is not None:
        return frame.early
    stack = frame.stack or []

    selected = ctx.sources.select("zoning.lookup", stack)
    registry_dim, gaps = selection_coverage(ctx.sources, "zoning.lookup", stack,
                                             selected)
    blocks: list[dict] = []
    failures = []
    queries: list[ArcGISQueryResult] = []
    parcel_note: str | None = None

    for m in selected:
        parcel_evidence_ref: str | None = None
        try:
            if pin:
                pq = await ctx.arcgis.query(m, "parcels",
                                            where_equals={"pin": pin},
                                            return_geometry=True)
                # The parcel query is a real consulted source too — its
                # geometry is what determines the zoning answer, and a
                # no-match here means the source WAS contacted even though
                # zoning never gets queried, not that nothing happened.
                parcel_ref = _source_entry(b, m, pq)
                if not pq.records:
                    blocks.append({"source_ref": parcel_ref,
                                   "source_id": m.id,
                                   "records": [], "record_count": 0,
                                   "note": f"no parcel with PIN {pin!r} in "
                                           f"{m.id}"})
                    queries.append(pq)
                    continue
                if len(pq.records) > 1:
                    parcel_note = (f"PIN {pin!r} matched "
                                   f"{len(pq.records)} parcel polygons; "
                                   "zoning uses the first, others listed in "
                                   "record_count.")
                parcel_evidence_ref = b.add_evidence(
                    source_ref=parcel_ref,
                    record_id=pq.records[0].record_id,
                    retrieved_at=pq.retrieved_at,
                    transformations=pq.transformations,
                    payload_hash=pq.payload_hash())
                geometry = dict(pq.records[0].geometry or {})
                geometry.setdefault("spatialReference", {"wkid": 4326})
                q = await ctx.arcgis.query(m, "zoning",
                                           intersect_geometry=geometry)
                q.transformations.append("parcel_geometry_intersection")
            else:
                q = await ctx.arcgis.query(m, "zoning",
                                           geometry_point=(lon, lat))
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        queries.append(q)
        block = _records_block(b, _source_entry(b, m, q), q, m)
        if parcel_evidence_ref is not None:
            block["parcel_evidence_ref"] = parcel_evidence_ref
        blocks.append(block)

    if any(blk["record_count"] for blk in blocks):
        b.warn(WarningCode.screening_only,
               "GIS zoning is a screening layer. The adopted zoning "
               "ordinance and official zoning map govern; confirm before "
               "any legal reliance.")

    execution = (ExecutionCoverage.complete if not failures
                 else ExecutionCoverage.failed if not blocks
                 else ExecutionCoverage.partial)
    total = sum(blk["record_count"] for blk in blocks)
    data = {"results": blocks}
    if parcel_note:
        data["parcel_note"] = parcel_note
    comparison = _compare(blocks, "district")
    if comparison:
        data["comparison"] = comparison
    coverage = Coverage(
        registry=registry_dim, execution=execution,
        pagination=_pagination_dim(queries),
        result=result_dim(total),
        jurisdictions_searched=stack if selected else [],
        jurisdictions_unavailable=gaps,
        source_failures=failures,
        known_limitations=sorted({lim for m in selected
                                  for lim in m.coverage.known_limitations}))
    return b.build(data, coverage)


GEO_TOOLS.register(ToolSpec(
    name="geo.find_parcel",
    description=(
        "Find parcel records in a Virginia jurisdiction by parcel PIN or by "
        "a lon/lat point. Pass the user's jurisdiction string as given — "
        "resolution and its ambiguities are handled here, and candidate "
        "lists must go back to the user unchosen. Results carry provenance "
        "and coverage; an empty result with coverage.registry='none' means "
        "Commonwealth has no source there, not that no parcel exists. For "
        "a street address, call geo.resolve_location first to get the "
        "jurisdiction and a coordinate."),
    toolset="default", contract_version="1", fn=find_parcel))
GEO_TOOLS.register(ToolSpec(
    name="geo.find_zoning",
    description=(
        "Find the zoning district(s) for a parcel PIN or lon/lat point in a "
        "Virginia jurisdiction. Screening only: results state the GIS "
        "layer's answer, never a legal determination — repeat the "
        "screening_only warning to the user. When two official sources are "
        "registered, both are queried and any disagreement is shown, not "
        "reconciled. Use geo.find_parcel first when you need the parcel "
        "record itself."),
    toolset="default", contract_version="1", fn=find_zoning))


def _bbox_of(geometry: dict | None) -> list[float] | None:
    rings = (geometry or {}).get("rings")
    if not rings:
        return None
    xs = [p[0] for ring in rings for p in ring]
    ys = [p[1] for ring in rings for p in ring]
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _boundary_plan(ctx: RuntimeContext,
                   j: Jurisdiction) -> tuple[str, dict[str, str]] | None:
    """(layer_key, where_equals) for one jurisdiction, or None when this
    source publishes no polygon at that level. The town layer keys on the
    publisher's 7-character state+place FIPS while the jurisdiction table
    stores the bare 5-character place code, so the state prefix is read
    from the table's own state row rather than hardcoded."""
    layer = BOUNDARY_LAYER_FOR_KIND.get(j.kind)
    if layer is None:
        return None
    if layer == "towns":
        if not j.place_fips:
            return None
        state = ctx.jurisdictions.get("va")
        state_fips = state.fips if state else None
        if not state_fips:
            return None
        return layer, {"place_fips": f"{state_fips}{j.place_fips}"}
    if not j.fips:
        return None
    return layer, {"fips": j.fips}


def _boundary_records(b: EnvelopeBuilder, src_ref: str, q: ArcGISQueryResult,
                      detail: str) -> list[dict]:
    rows = []
    for r in q.records:
        ev = b.add_evidence(source_ref=src_ref, record_id=r.record_id,
                            retrieved_at=q.retrieved_at,
                            transformations=q.transformations,
                            payload_hash=q.payload_hash())
        row = {**r.canonical, "record_id": r.record_id, "evidence_ref": ev}
        # The layer publishes no layer-level edit date, but every feature
        # carries its own LASTUPDATE. Surfacing it converted gives each
        # boundary the vintage the layer itself withholds.
        raw_update = row.pop("last_update", None)
        row["record_updated_at"] = _epoch_ms_to_iso(raw_update)
        geometry = r.geometry or {}
        rings = geometry.get("rings") or []
        row["bbox"] = _bbox_of(geometry)
        row["ring_count"] = len(rings)
        row["vertex_count"] = sum(len(ring) for ring in rings)
        if r.centroid:
            row["centroid"] = {"lon": r.centroid.get("x"),
                               "lat": r.centroid.get("y"),
                               "note": "Publisher's centre-of-mass label "
                                       "point. NOT guaranteed to lie inside "
                                       "this jurisdiction: a Virginia county "
                                       "that encloses an independent city is "
                                       "a donut and its centroid falls in the "
                                       "city. Never use it to decide "
                                       "containment."}
        if detail == "full":
            row["geometry"] = {"type": "esriPolygon", "spatialReference":
                               {"wkid": 4326}, "rings": rings}
        rows.append(row)
    return rows


def _epoch_ms_to_iso(value: object) -> str | None:
    if not isinstance(value, (int, float)) or not value:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


async def find_boundaries(ctx: RuntimeContext, jurisdiction: str,
                          detail: str = "concise") -> Envelope:
    b = _builder(ctx, "geo.find_boundaries")
    if detail not in ("concise", "full"):
        raise InvalidQuery(
            f"detail must be 'concise' or 'full', not {detail!r}")

    frame = _resolve_frame(ctx, b, jurisdiction)
    if frame.early is not None:
        return frame.early
    stack = frame.stack or []
    j = ctx.jurisdictions.get(stack[0])
    assert j is not None  # stack[0] came from the table itself

    selected = ctx.sources.select("boundary.lookup", stack)
    registry_dim, gaps = selection_coverage(ctx.sources, "boundary.lookup",
                                            stack, selected)

    plan = _boundary_plan(ctx, j)
    layered = [{"id": p.id, "relationship": "parent-" + p.kind.value}
               for p in ctx.jurisdictions.parents_of(j)]
    base: dict = {
        "jurisdiction": {"id": j.id, "name": j.name, "kind": j.kind.value},
        "layered_authorities": layered,
    }

    if plan is None:
        # Not a registry gap and not an outage: a registered source was
        # selectable, it simply publishes nothing at this level. Saying
        # "empty" without saying why would read as "no such boundary".
        base["results"] = []
        base["note"] = (
            f"{j.name} is a {j.kind.value}; the registered boundary "
            "sources publish polygons for counties, independent cities, "
            "and incorporated towns only. This is a gap in what the "
            "publisher covers, not evidence that no boundary exists.")
        return b.build(base, Coverage(
            registry=registry_dim, execution=ExecutionCoverage.complete,
            pagination=PaginationCoverage.complete,
            result=ResultCoverage.empty,
            jurisdictions_searched=stack if selected else [],
            jurisdictions_unavailable=gaps,
            known_limitations=sorted({lim for m in selected
                                      for lim in m.coverage.known_limitations})))

    layer_key, where = plan
    blocks: list[dict] = []
    failures = []
    queries: list[ArcGISQueryResult] = []
    for m in selected:
        try:
            q = await ctx.arcgis.query(
                m, layer_key, where_equals=where, return_geometry=True,
                return_centroid=True,
                simplify_tolerance=BOUNDARY_SIMPLIFY_DEGREES)
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        queries.append(q)
        src_ref = _source_entry(b, m, q)
        block = {"source_ref": src_ref, "source_id": m.id,
                 "layer": layer_key,
                 "records": _boundary_records(b, src_ref, q, detail),
                 "record_count": len(q.records)}
        if len(q.records) > 1:
            block["note"] = (
                f"{len(q.records)} separate polygons carry this "
                "jurisdiction's identifier. They are all returned; none is "
                "picked as the 'real' one. Prince George County is the "
                "known case — see the source's known_limitations.")
        blocks.append(block)

    total = sum(blk["record_count"] for blk in blocks)
    if total:
        b.warn(WarningCode.boundary_precision,
               "Boundary geometry is generalized to "
               f"{BOUNDARY_SIMPLIFY_DEGREES} degrees (~22 m) so it fits an "
               "inline response, and the publisher disclaims it for legal "
               "description or survey use. Do not use it to decide which "
               "side of a line a specific address falls on.")
    if detail == "concise" and total:
        base["geometry_note"] = (
            "Vertex coordinates are omitted at detail='concise'; bbox, "
            "centroid, and vertex counts are shown. Pass detail='full' "
            "for the generalized rings.")

    execution = (ExecutionCoverage.complete if not failures
                 else ExecutionCoverage.failed if not blocks
                 else ExecutionCoverage.partial)
    base["results"] = blocks
    return b.build(base, Coverage(
        registry=registry_dim, execution=execution,
        pagination=_pagination_dim(queries), result=result_dim(total),
        jurisdictions_searched=stack if selected else [],
        jurisdictions_unavailable=gaps, source_failures=failures,
        known_limitations=sorted({lim for m in selected
                                  for lim in m.coverage.known_limitations})))


GEO_TOOLS.register(ToolSpec(
    name="geo.find_boundaries",
    description=(
        "Get a Virginia jurisdiction's official boundary: FIPS, GNIS, "
        "area, jurisdiction type, bounding box, and the publisher's own "
        "centroid. Use to confirm WHICH government's territory is meant "
        "and how big it is. Independent cities are returned as their own "
        "territory, never as part of the county sharing their name. "
        "Screening geometry only — it is generalized and the publisher "
        "disclaims survey use, so never decide from it which side of a "
        "boundary an address sits on. Pass detail='full' for vertices. "
        "Not a containment test: to find which jurisdiction covers a "
        "point, use registry.resolve_jurisdiction with lon/lat."),
    toolset="default", contract_version="1", fn=find_boundaries))


# --- addresses (GitHub issue #4) -------------------------------------------

async def find_address(ctx: RuntimeContext, jurisdiction: str,
                       address: str = "", lon: float | None = None,
                       lat: float | None = None) -> Envelope:
    b = _builder(ctx, "geo.find_address")
    if (lon is None) != (lat is None):
        raise InvalidQuery("a point needs both lon and lat")
    if bool(address) == (lon is not None and lat is not None):
        raise InvalidQuery("pass exactly one of `address` or a lon/lat point")

    frame = _resolve_frame(ctx, b, jurisdiction)
    if frame.early is not None:
        return frame.early
    stack = frame.stack or []

    selected = ctx.sources.select("address.lookup", stack)
    registry_dim, gaps = selection_coverage(ctx.sources, "address.lookup",
                                            stack, selected)
    blocks: list[dict] = []
    failures = []
    queries: list[ArcGISQueryResult] = []
    for m in selected:
        try:
            if address:
                # A prefix match on the publisher's own spelling, scoped to
                # the jurisdiction so a street name shared across Virginia
                # does not answer from the wrong locality.
                where = _scoped_where(ctx, m, "addresses", stack, {})
                q = await ctx.arcgis.query(
                    m, "addresses", where_equals=where or None,
                    where_prefix={"full_address": address.upper()})
            else:
                q = await ctx.arcgis.query(m, "addresses",
                                           geometry_point=(lon, lat),
                                           distance_meters=ADDRESS_POINT_RADIUS_M)
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        queries.append(q)
        block = _records_block(b, _source_entry(b, m, q), q, m)
        for row in block["records"]:
            row["record_updated_at"] = _epoch_ms_to_iso(
                row.pop("last_update", None))
            # The postal place and the government can disagree, and the
            # disagreement is the whole reason this field is labelled.
            row["place_note"] = (
                "`po_name` is a postal city, not a government: a Fairfax "
                "County address reads ALEXANDRIA. `landmark_name` is a "
                "facility name where the publisher has one, not a place. "
                "The jurisdiction for this record is `locality` / `fips`.")
        blocks.append(block)

    if any(blk["record_count"] for blk in blocks):
        b.warn(WarningCode.screening_only,
               "An address point is the publisher's record of an address, "
               "not a legal description or a survey, and a locality behind "
               "on its data submission looks the same as an address that "
               "does not exist.")

    execution = (ExecutionCoverage.complete if not failures
                 else ExecutionCoverage.failed if not blocks
                 else ExecutionCoverage.partial)
    total = sum(blk["record_count"] for blk in blocks)
    data: dict = {"results": blocks}
    comparison = _compare(blocks, "full_address")
    if comparison:
        data["comparison"] = comparison
    return b.build(data, Coverage(
        registry=registry_dim, execution=execution,
        pagination=_pagination_dim(queries), result=result_dim(total),
        jurisdictions_searched=stack if selected else [],
        jurisdictions_unavailable=gaps, source_failures=failures,
        known_limitations=sorted({lim for m in selected
                                  for lim in m.coverage.known_limitations})))


GEO_TOOLS.register(ToolSpec(
    name="geo.find_address",
    description=(
        "Find address-point records in a Virginia jurisdiction, by address "
        "string or by a lon/lat point. The string path is a PREFIX match "
        "on the publisher's own spelling (\"6800 BEULAH ST\"), not a fuzzy "
        "search — use geo.resolve_location when the input is a typed "
        "address that needs interpreting. A record's `po_name` is a POSTAL "
        "city and is never the government: a Fairfax County address reads "
        "\"ALEXANDRIA\". Read `locality` and `fips` for the jurisdiction. "
        "An empty result means this "
        "publisher has no record, which is not the same as no such "
        "address existing."),
    toolset="spatial", contract_version="1", fn=find_address))


# --- address and ZIP resolution (GitHub issue #3) --------------------------

# What a ZIP code is asked of. The composite locator geocodes a ZIP to one
# centroid, which for a ZIP spanning several localities answers a question
# nobody asked. The address-point layer carries both ZIP_5 and FIPS per
# record, so one DISTINCT query returns every locality the ZIP actually
# touches — the difference between a convenience and an answer.
ZIP_PATTERN = re.compile(r"^\d{5}$")


def _geocode_source(b: EnvelopeBuilder, m: SourceManifest,
                    g: GeocodeResult) -> str:
    return b.add_source(
        source_id=m.id, publisher=m.publisher.agency, system=m.adapter.type,
        dataset=m.name, jurisdiction=m.jurisdiction,
        authority_level=m.publisher.authority_level,
        access_path=AccessPath.cache if g.from_cache else AccessPath.live,
        source_updated_at=None, retrieved_at=g.retrieved_at,
        cache_age_seconds=g.cache_age_seconds)


async def _resolve_zip(ctx: RuntimeContext, b: EnvelopeBuilder,
                       zip_code: str) -> Envelope:
    """Every locality a ZIP touches, from the address-point layer.

    design/jurisdiction-resolution.md § 3 case 5: a one-to-many ZIP that
    resolves to one jurisdiction is a bug, not a convenience. So this never
    picks — a ZIP inside one locality resolves, and a ZIP spanning several
    comes back as candidates with requires_user_choice."""
    selected = ctx.sources.select("address.lookup", ["va"])
    registry_dim, gaps = selection_coverage(ctx.sources, "address.lookup",
                                            ["va"], selected)
    if not selected:
        return b.build(
            {"resolved": None, "candidates": [], "zip_code": zip_code,
             "note": "No address source is registered, so a ZIP cannot be "
                     "mapped to the localities it covers. This is a "
                     "Commonwealth coverage gap, not a statement about "
                     "the ZIP."},
            Coverage(registry=registry_dim,
                     execution=ExecutionCoverage.complete,
                     pagination=PaginationCoverage.complete,
                     result=ResultCoverage.empty,
                     jurisdictions_unavailable=gaps))
    m = selected[0]
    try:
        # int, not str: ZIP_5 is a numeric column on this layer and the
        # quoted form is rejected. The tool's own input stays a string,
        # because a ZIP with a leading zero is not the number it looks
        # like — the cast happens here, after the 5-digit check.
        q = await ctx.arcgis.query(
            m, "addresses", where_equals={"zip_code": int(zip_code)},
            distinct_fields=["fips", "locality"])
    except CommonwealthError as err:
        return b.build(
            {"resolved": None, "candidates": [], "zip_code": zip_code,
             "note": "The address source could not be reached, so this ZIP "
                     "was not mapped. That is an outage, not an answer."},
            Coverage(registry=registry_dim,
                     execution=ExecutionCoverage.failed,
                     pagination=PaginationCoverage.complete,
                     result=ResultCoverage.empty,
                     source_failures=[failure(m.id, err.code, str(err))]))

    src_ref = _source_entry(b, m, q)
    matches = []
    for r in q.records:
        b.add_evidence(source_ref=src_ref, record_id=r.record_id,
                       retrieved_at=q.retrieved_at,
                       transformations=q.transformations,
                       payload_hash=q.payload_hash())
        fips = str(r.canonical.get("fips") or "")
        j = ctx.jurisdictions.by_fips(fips)
        matches.append({"fips": fips,
                        "source_name": r.canonical.get("locality"),
                        "id": j.id if j else None,
                        "name": j.name if j else r.canonical.get("locality"),
                        "kind": j.kind.value if j else None})
    matches.sort(key=lambda mm: mm["fips"])

    data: dict = {"zip_code": zip_code, "source_ref": src_ref,
                  "localities_touched": matches}
    if not matches:
        data["resolved"] = None
        data["candidates"] = []
        data["note"] = (
            f"No address point in the registered layer carries ZIP "
            f"{zip_code}. That is what this publisher has on record, not "
            "proof the ZIP does not exist or covers nothing in Virginia.")
        return b.build(data, Coverage(
            registry=registry_dim, execution=ExecutionCoverage.complete,
            pagination=_pagination_dim([q]), result=ResultCoverage.empty,
            jurisdictions_searched=["va"],
            known_limitations=sorted(m.coverage.known_limitations)))

    if len(matches) == 1:
        only = matches[0]
        data["resolved"] = ({"id": only["id"], "name": only["name"],
                             "kind": only["kind"], "fips": only["fips"],
                             "basis": "zip_unique"}
                            if only["id"] else None)
        data["candidates"] = []
        if only["id"] is None:
            data["note"] = (
                f"ZIP {zip_code} covers one locality, {only['source_name']}, "
                "which is not in Commonwealth's jurisdiction table.")
        return b.build(data, Coverage(
            registry=registry_dim, execution=ExecutionCoverage.complete,
            pagination=_pagination_dim([q]), result=ResultCoverage.hit,
            jurisdictions_searched=["va"],
            known_limitations=sorted(m.coverage.known_limitations)))

    data["resolved"] = None
    data["candidates"] = [
        {"id": mm["id"], "name": mm["name"], "kind": mm["kind"],
         "distinguisher": f"one of {len(matches)} localities ZIP "
                          f"{zip_code} covers (FIPS {mm['fips']})"}
        for mm in matches]
    data["note"] = (
        f"ZIP {zip_code} spans {len(matches)} Virginia localities. A ZIP is "
        "a postal delivery route, not a government boundary, and picking "
        "one of these would be a guess. Present the candidates to the "
        "user, or geocode the full street address instead.")
    return b.build(data, Coverage(
        registry=registry_dim, execution=ExecutionCoverage.complete,
        pagination=_pagination_dim([q]), result=ResultCoverage.hit,
        jurisdictions_searched=["va"],
        known_limitations=sorted(m.coverage.known_limitations)),
        requires_user_choice=True)


async def resolve_location(ctx: RuntimeContext, address: str = "",
                           zip_code: str = "") -> Envelope:
    b = _builder(ctx, "geo.resolve_location")
    if bool(address) == bool(zip_code):
        raise InvalidQuery(
            "pass exactly one of `address` or `zip_code` — there is no "
            "precedence rule between them, and silently preferring one "
            "would hide a contradiction between what you typed and where "
            "it points")
    if zip_code:
        if not ZIP_PATTERN.match(zip_code.strip()):
            raise InvalidQuery(
                f"{zip_code!r} is not a 5-digit ZIP code. ZIP+4 is not "
                "supported: the +4 narrows a delivery route, not a "
                "government boundary, and this tool answers about "
                "governments.")
        return await _resolve_zip(ctx, b, zip_code.strip())

    selected = ctx.sources.select("geocode.address", ["va"])
    registry_dim, gaps = selection_coverage(ctx.sources, "geocode.address",
                                            ["va"], selected)
    if not selected:
        return b.build(
            {"resolved": None, "candidates": [], "address": address,
             "note": "No geocoder is registered, so an address cannot be "
                     "turned into a coordinate. Pass a lon/lat point to "
                     "registry.resolve_jurisdiction instead. This is a "
                     "Commonwealth coverage gap, not a statement about "
                     "the address."},
            Coverage(registry=registry_dim,
                     execution=ExecutionCoverage.complete,
                     pagination=PaginationCoverage.complete,
                     result=ResultCoverage.empty,
                     jurisdictions_unavailable=gaps))

    m = selected[0]
    try:
        g = await ctx.geocoder.geocode(m, address)
    except CommonwealthError as err:
        return b.build(
            {"resolved": None, "candidates": [], "address": address,
             "note": "The geocoder could not be reached, so this address "
                     "was not placed. That is an outage, not an address "
                     "that does not exist."},
            Coverage(registry=registry_dim,
                     execution=ExecutionCoverage.failed,
                     pagination=PaginationCoverage.complete,
                     result=ResultCoverage.empty,
                     source_failures=[failure(m.id, err.code, str(err))]))

    geo_ref = _geocode_source(b, m, g)
    confident = g.confident()
    data: dict = {"address": address,
                  "geocode": {"source_ref": geo_ref,
                              "min_score": g.min_score,
                              "candidate_count": len(g.candidates)}}

    if not confident:
        # Below the declared threshold, or nothing at all. Both are the
        # same instruction to the caller — do not proceed on this — but
        # they are different facts, so they read differently.
        data["resolved"] = None
        data["candidates"] = [
            {**c.canonical(), "distinguisher":
                f"score {c.score} is under the {g.min_score} threshold; "
                f"matched by {c.matched_by or 'an unnamed locator element'}"}
            for c in g.candidates[:INLINE_RECORD_CAP]]
        data["note"] = (
            f"The geocoder returned no match at or above score "
            f"{g.min_score}. " + (
                "Nothing was returned at all, so the address may be "
                "outside Virginia (the publisher states the locator "
                "covers the Commonwealth only) or spelled in a way the "
                "locator does not recognise."
                if not g.candidates else
                "The weaker candidates are listed; present them to the "
                "user and let them choose, rather than picking one."))
        return b.build(data, Coverage(
            registry=registry_dim, execution=ExecutionCoverage.complete,
            pagination=PaginationCoverage.complete,
            result=result_dim(len(g.candidates)),
            jurisdictions_searched=["va"],
            known_limitations=sorted(m.coverage.known_limitations)),
            requires_user_choice=bool(g.candidates))

    best = confident[0]
    ev = b.add_evidence(source_ref=geo_ref, record_id=best.record_id,
                        retrieved_at=g.retrieved_at,
                        transformations=g.transformations,
                        payload_hash=g.payload_hash())
    data["geocode"].update({**best.canonical(), "evidence_ref": ev})
    if best.address_type.lower() in ("postal", "postalext", "locality"):
        b.warn(WarningCode.boundary_precision,
               f"The locator matched this address at the {best.address_type} "
               "level, which is a centroid for a whole postal or place "
               "area rather than the address itself. The jurisdiction "
               "below is the one containing that centroid, which is not "
               "necessarily the one containing the address.")

    # A geocode is never a resolution on its own: the point goes through
    # the same point-in-polygon path registry.resolve_jurisdiction uses,
    # and the government that owns the polygon is the answer.
    c = await resolve_point(ctx, b, best.lon, best.lat)
    if c.manifest is None or c.unreachable:
        data["resolved"] = None
        data["candidates"] = []
        data["note"] = (
            "The address geocoded, but the boundary source that would "
            "place the coordinate in a jurisdiction "
            + ("is not registered." if c.manifest is None
               else "could not be reached — an outage, not an answer.")
            + " The coordinate is in `geocode` and can be passed to "
              "registry.resolve_jurisdiction later.")
        return b.build(data, Coverage(
            registry=(RegistryCoverage.partial if c.manifest is None
                      else registry_dim),
            execution=(ExecutionCoverage.complete if c.manifest is None
                       else ExecutionCoverage.partial),
            pagination=PaginationCoverage.complete,
            result=ResultCoverage.hit,
            jurisdictions_unavailable=c.gaps,
            source_failures=c.failures))

    if c.empty:
        data["resolved"] = None
        data["candidates"] = []
        data["note"] = (
            "The address geocoded to a coordinate that no Virginia "
            "locality polygon contains. The locator covers the "
            "Commonwealth only, so this usually means the match landed "
            "just outside the mapped boundary rather than that the "
            "address is unreal.")
        return b.build(data, Coverage(
            registry=registry_dim, execution=ExecutionCoverage.complete,
            pagination=PaginationCoverage.complete,
            result=ResultCoverage.hit,
            jurisdictions_searched=["va"], source_failures=c.failures))

    leaf = c.leaf
    assert leaf is not None
    resolved_j = leaf["jurisdiction"]
    if resolved_j is not None:
        data["resolved"] = {"id": resolved_j.id, "name": resolved_j.name,
                            "kind": resolved_j.kind.value,
                            "fips": resolved_j.fips,
                            "basis": "geocode_then_point_in_polygon"}
    else:
        data["resolved"] = None
        data["unmapped_match"] = {
            "source_name": leaf["source_name"],
            "source_fips": leaf["source_fips"], "layer": leaf["layer"],
            "note": "The boundary source places this address in the "
                    "jurisdiction named here, which is not in "
                    "Commonwealth's jurisdiction table. The place is "
                    "real; the gap is ours."}
    data["candidates"] = []
    data["layered_authorities"] = c.layered(ctx)
    if best.postal_city and resolved_j is not None and \
            best.postal_city.lower() not in resolved_j.name.lower():
        # design/jurisdiction-resolution.md § 3 case 1. The postal city and
        # the government routinely differ, and an agent that reads the
        # mailing address as the jurisdiction gets a plausible wrong
        # government's records.
        data["postal_city_note"] = (
            f"The mailing address says {best.postal_city.title()}; the "
            f"government is {resolved_j.name}. A postal city is a delivery "
            "route name, not a jurisdiction, and these disagree often in "
            "Virginia. The government is what applies.")
    warn_if_near_a_border(b, c)
    if c.nearby:
        data["nearby_jurisdictions"] = c.nearby

    return b.build(data, Coverage(
        registry=registry_dim,
        execution=(ExecutionCoverage.partial if c.failures
                   else ExecutionCoverage.complete),
        pagination=PaginationCoverage.complete,
        result=ResultCoverage.hit,
        jurisdictions_searched=["va"], source_failures=c.failures,
        known_limitations=sorted(
            set(m.coverage.known_limitations)
            | set(c.manifest.coverage.known_limitations))))


GEO_TOOLS.register(ToolSpec(
    name="geo.resolve_location",
    description=(
        "Turn a Virginia street address or a 5-digit ZIP into the "
        "government that covers it. Use this FIRST when the user gives an "
        "address — the other tools take a jurisdiction name or a "
        "coordinate, not an address. An address is geocoded and the "
        "resulting point is placed by point-in-polygon; the geocoder's own "
        "city field is a POSTAL city and is never the answer (a Fairfax "
        "County address reads 'Alexandria'). A ZIP returns every locality "
        "it touches: ZIPs are delivery routes and cross government "
        "boundaries constantly, so a multi-locality ZIP comes back as "
        "candidates with requires_user_choice and must go to the user "
        "unchosen. Pass exactly one of `address` or `zip_code`."),
    toolset="default", contract_version="1", fn=resolve_location))
