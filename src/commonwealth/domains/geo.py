"""Geo tools: find_parcel and find_zoning (design/domain-servers.md § 3).

Selection discipline is ../../../design/architecture.md decision 0005 as Chosen: up to the top two
selectable sources are queried and every per-source result is surfaced;
nothing reconciles two official answers into one. Ambiguous jurisdictions
return candidates with requires_user_choice (../../../design/architecture.md decision 0004). Registry gaps,
outages, and empty results are three different coverage shapes, never one.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..adapters.arcgis import ArcGISQueryResult
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

GEO_TOOLS = ToolRegistry(package="geo")

INLINE_RECORD_CAP = 25

# Degrees of allowable offset handed to the platform's own generalization.
# ~0.0002 deg is roughly 22 m at Virginia's latitude: enough to shrink a
# county polygon from ~679 KB / 16,641 vertices to ~11 KB / 523 and still
# draw the right shape. It is lossy, so it is declared in the record, in
# `transformations`, and in a boundary_precision warning — never silently.
BOUNDARY_SIMPLIFY_DEGREES = 0.0002

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
    if bool(pin) == (lon is not None and lat is not None):
        raise InvalidQuery("pass exactly one of `pin` or a lon/lat point")
    if (lon is None) != (lat is None):
        raise InvalidQuery("a point needs both lon and lat")

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
    if bool(pin) == (lon is not None and lat is not None):
        raise InvalidQuery("pass exactly one of `pin` or a lon/lat point")
    if (lon is None) != (lat is None):
        raise InvalidQuery("a point needs both lon and lat")

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
        "Commonwealth has no source there, not that no parcel exists. Not "
        "for street addresses yet (no geocoding in this release)."),
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
