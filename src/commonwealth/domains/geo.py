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
from ..adapters.arcgis_geocode import (GeocodeCandidate,
                                       GeocodeResult)
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

# How many parcel polygons one PIN may be intersected against. Each is
# another request to a government service, and a PIN matching more
# than a handful is a data problem rather than a parcel — the answer
# says how many were used and how many were not.
MAX_PARCEL_POLYGONS = 5

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
        if resolution.matched_former_name:
            # Every geo tool's description tells the caller to pass the
            # jurisdiction string as given, so a historical name reaches
            # here as readily as it reaches registry.resolve_jurisdiction
            # — and answering it silently returns current data under a
            # government that no longer exists.
            b.warn(WarningCode.alias_match,
                   f"{resolution.matched_former_name!r} names a Virginia "
                   "government that no longer exists under that name. "
                   f"This answer is about {j.name}, which governs that "
                   "territory now. A record using the old name predates "
                   "the change; check its date before treating this as "
                   "current.")
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
        cache_age_seconds=q.cache_age_seconds,
        terms_gap=m.access.terms_gap)


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
        # A list, per design/provenance-envelope.md § 2, even where a
        # record rests on exactly one piece of evidence today. A record
        # that rests on several is not hypothetical — a PIN matching
        # several parcel polygons is one — and a shape that changes when
        # the second one arrives is a breaking change deferred rather
        # than avoided.
        rows.append({**r.canonical, "record_id": r.record_id,
                     "evidence_refs": [ev]})
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


def _jurisdiction_names(ctx: RuntimeContext, stack: list[str]) -> list[str]:
    """Every way the leaf jurisdiction's name is written, for a layer that
    keys on names rather than codes. Both the table's own name and its
    aliases go in, because VDOT writes "Fairfax County" for a county and
    "City of Fairfax" for an independent city, which are the table's name
    and its alias respectively."""
    j = ctx.jurisdictions.get(stack[0]) if stack else None
    if j is None:
        return []
    names = [j.name] + list(j.aliases)
    # A town's name in the table carries a "(town)" suffix the publisher
    # does not use; its "Town of X" alias is the form that matches.
    return [n for n in names if "(" not in n]


@dataclass
class _Scope:
    """A jurisdiction filter and the jurisdiction it actually narrows to.

    The two are not always the same. A town has no FIPS of its own — the
    code is its county's — so a layer keyed on FIPS can only be narrowed
    to the county. That filter is still worth applying (it is a correct
    superset, and it is what stops a locality-scoped PIN matching another
    locality's parcel on a statewide layer), but a result scoped to the
    county and labelled with the town is a claim the data does not
    support. `narrowed_to` is what the tools report.
    """

    groups: list[dict[str, str]] | None = None
    narrowed_to: str | None = None
    # The declared scope mode, so a caller can tell a name-keyed layer
    # from a code-keyed one without re-reading the manifest.
    mode: str | None = None

    def note(self, ctx: RuntimeContext, requested: str) -> str | None:
        if self.narrowed_to is None or self.narrowed_to == requested:
            return None
        wanted = ctx.jurisdictions.get(requested)
        got = ctx.jurisdictions.get(self.narrowed_to)
        return (
            f"This source has no key for {wanted.name if wanted else requested}"
            f", so the query was narrowed to "
            f"{got.name if got else self.narrowed_to} instead. The results "
            "cover that whole jurisdiction, not just the one asked about.")


def _fips_scope(ctx: RuntimeContext, stack: list[str]) -> tuple[str | None,
                                                                str | None]:
    """(fips, the jurisdiction id it belongs to) walking up the stack."""
    for jid in stack:
        j = ctx.jurisdictions.get(jid)
        if j and j.fips:
            return j.fips, j.id
    return None, None


def _jurisdiction_scope(ctx: RuntimeContext, m: SourceManifest,
                        layer_key: str, stack: list[str]) -> _Scope:
    """The filter narrowing a layer to one jurisdiction, and which
    jurisdiction it reaches, driven by the layer's own
    `jurisdiction_scope` declaration.

    `groups` is None when the layer declares no scope or the stack
    supplies nothing to scope by. The query then runs unscoped and the
    tool names which sources it could not narrow, so a statewide answer is
    never read as a local one."""
    scope = ctx.arcgis.jurisdiction_scope(m, layer_key)
    if scope is None or scope.mode == "none":
        return _Scope()
    if scope.mode == "jurisdiction_names":
        names = _jurisdiction_names(ctx, stack)
        field = scope.fields[0]
        # Names key on the leaf directly: VDOT writes "Town of Vienna",
        # which is the town and not its county.
        return _Scope([{field: n} for n in names] or None,
                      stack[0] if names and stack else None, scope.mode)
    fips, owner = _fips_scope(ctx, stack)
    if fips is None:
        return _Scope()
    if scope.mode == "fips":
        return _Scope([{scope.fields[0]: fips}], owner, scope.mode)
    return _Scope([{field: fips} for field in scope.fields], owner,
                  scope.mode)


def _jurisdiction_filter(ctx: RuntimeContext, m: SourceManifest,
                         layer_key: str, stack: list[str],
                         ) -> list[dict[str, str]] | None:
    return _jurisdiction_scope(ctx, m, layer_key, stack).groups


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
    fips, _ = _fips_scope(ctx, stack)
    if fips is None:
        return where_equals
    return {**where_equals, "fips": fips}


def _widened_note(ctx: RuntimeContext, m: SourceManifest, layer_key: str,
                  stack: list[str]) -> str | None:
    """The sentence a tool prints when `_scoped_where` narrowed to
    something broader than the jurisdiction asked about."""
    owner = _scoped_where_owner(ctx, m, layer_key, stack)
    return _Scope(narrowed_to=owner).note(ctx, stack[0]) if owner else None


def _scoped_where_owner(ctx: RuntimeContext, m: SourceManifest,
                        layer_key: str, stack: list[str]) -> str | None:
    """Which jurisdiction `_scoped_where`'s filter actually reaches, or
    None when it applies no filter. A town borrows its county's FIPS, so
    this is not always `stack[0]`."""
    if m.jurisdiction == stack[0]:
        return stack[0]
    if "fips" not in ctx.arcgis.mapped_canonical_fields(m, layer_key):
        return None
    return _fips_scope(ctx, stack)[1]


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
        parcel_evidence_refs: list[str] = []
        polygons_used = 0
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
                # Every polygon the PIN matched, up to a bound. Taking the
                # first was right for the count and wrong for the answer:
                # a parcel split across polygons can carry more than one
                # zoning district, and reporting one district for it is
                # correct about part of the ground and silent about the
                # rest.
                used = pq.records[:MAX_PARCEL_POLYGONS]
                polygons_used = len(used)
                if len(pq.records) > len(used):
                    parcel_note = (
                        f"PIN {pin!r} matched {len(pq.records)} parcel "
                        f"polygons; the first {len(used)} were intersected "
                        "and the rest were not. Narrow the query — this "
                        "answer covers part of the parcel.")
                elif len(used) > 1:
                    parcel_note = (
                        f"PIN {pin!r} matched {len(used)} parcel polygons. "
                        "All were intersected and the districts below are "
                        "the union across them, so more than one district "
                        "here means the parcel is split, not that the "
                        "sources disagree.")
                merged: dict[str, object] = {}
                # Which parcel polygon produced which zoning record.
                # Attaching every parcel ref to every district said each
                # one was supported by polygons it never intersected —
                # which for a parcel split across two districts is a
                # false claim about where each district applies.
                produced_by: dict[str, list[str]] = {}
                q = None
                for parcel in used:
                    this_ref = b.add_evidence(
                        source_ref=parcel_ref, record_id=parcel.record_id,
                        retrieved_at=pq.retrieved_at,
                        transformations=pq.transformations,
                        payload_hash=pq.payload_hash())
                    parcel_evidence_refs.append(this_ref)
                    geometry = dict(parcel.geometry or {})
                    geometry.setdefault("spatialReference", {"wkid": 4326})
                    zq = await ctx.arcgis.query(m, "zoning",
                                                intersect_geometry=geometry)
                    zq.transformations.append("parcel_geometry_intersection")
                    for rec in zq.records:
                        # One zoning polygon can touch several parcel
                        # polygons; deduplicating on the record id keeps a
                        # district from being counted twice for one parcel.
                        merged.setdefault(rec.record_id, rec)
                        produced_by.setdefault(rec.record_id, []).append(
                            this_ref)
                    if q is None:
                        q = zq
                    else:
                        q.exceeded_transfer_limit |= zq.exceeded_transfer_limit
                        q.cache_age_seconds = max(q.cache_age_seconds,
                                                  zq.cache_age_seconds)
                        q.retrieved_at = min(q.retrieved_at, zq.retrieved_at)
                        q.from_cache = q.from_cache or zq.from_cache
                assert q is not None  # `used` is non-empty here
                if polygons_used > 1:
                    q.transformations.append(
                        f"parcel_polygons_unioned:{polygons_used}")
                q.records = list(merged.values())
            else:
                q = await ctx.arcgis.query(m, "zoning",
                                           geometry_point=(lon, lat))
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        queries.append(q)
        block = _records_block(b, _source_entry(b, m, q), q, m)
        if parcel_evidence_refs:
            block["parcel_evidence_refs"] = parcel_evidence_refs
            block["parcel_polygons_intersected"] = polygons_used
            # Each district rests on the parcel polygons that ACTUALLY
            # produced it, which for a split parcel is a subset — this is
            # the case design/provenance-envelope.md § 2's array exists
            # for, and attaching all of them to all of them would have
            # answered it wrongly.
            for row in block["records"]:
                row["evidence_refs"] = (
                    list(row["evidence_refs"])
                    + produced_by.get(row["record_id"], []))
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
        row = {**r.canonical, "record_id": r.record_id,
               "evidence_refs": [ev]}
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
            # Scoped on BOTH paths. The string path needs it so a street
            # name shared across Virginia does not answer from the wrong
            # locality; the point path needs it because the buffer reaches
            # 100 m and a point near a line pulls in the neighbouring
            # locality's addresses — which the envelope would then report
            # under `jurisdictions_searched: [the one you asked for]`.
            where = _scoped_where(ctx, m, "addresses", stack, {})
            scope_note = _widened_note(ctx, m, "addresses", stack)
            if address:
                q = await ctx.arcgis.query(
                    m, "addresses", where_equals=where or None,
                    where_prefix={"full_address": address.upper()})
            else:
                q = await ctx.arcgis.query(
                    m, "addresses", where_equals=where or None,
                    geometry_point=(lon, lat),
                    distance_meters=ADDRESS_POINT_RADIUS_M)
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        queries.append(q)
        block = _records_block(b, _source_entry(b, m, q), q, m)
        if scope_note:
            block["widened_scope"] = scope_note
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
    toolset="default", contract_version="1", fn=find_address))


# --- address and ZIP resolution (GitHub issue #3) --------------------------

# What a ZIP code is asked of. The composite locator geocodes a ZIP to one
# centroid, which for a ZIP spanning several localities answers a question
# nobody asked. The address-point layer carries both ZIP_5 and FIPS per
# record, so one DISTINCT query returns every locality the ZIP actually
# touches — the difference between a convenience and an answer.
ZIP_PATTERN = re.compile(r"^\d{5}$")

# How many distinct confident geocode coordinates get placed before the
# tool stops checking whether they disagree. Each placement is two more
# queries against a government service, and a locator returning more
# than a handful of equally confident matches in different places has
# already told the caller the address is underspecified.
MAX_GEOCODE_CONTAINMENT_CHECKS = 4


def _geocode_source(b: EnvelopeBuilder, m: SourceManifest,
                    g: GeocodeResult) -> str:
    return b.add_source(
        source_id=m.id, publisher=m.publisher.agency, system=m.adapter.type,
        dataset=m.name, jurisdiction=m.jurisdiction,
        authority_level=m.publisher.authority_level,
        access_path=AccessPath.cache if g.from_cache else AccessPath.live,
        source_updated_at=None, retrieved_at=g.retrieved_at,
        cache_age_seconds=g.cache_age_seconds,
        terms_gap=m.access.terms_gap)


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
        ev = b.add_evidence(source_ref=src_ref, record_id=r.record_id,
                            retrieved_at=q.retrieved_at,
                            transformations=q.transformations,
                            payload_hash=q.payload_hash())
        fips = str(r.canonical.get("fips") or "")
        j = ctx.jurisdictions.by_fips(fips)
        # Each locality is a material record resting on one distinct
        # publisher tuple, so it names that tuple
        # (design/provenance-envelope.md § 2). Creating the evidence and
        # discarding its id left the whole answer unlinkable.
        matches.append({"fips": fips,
                        "source_name": r.canonical.get("locality"),
                        "id": j.id if j else None,
                        "name": j.name if j else r.canonical.get("locality"),
                        "kind": j.kind.value if j else None,
                        "evidence_refs": [ev]})
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
                             "basis": "zip_unique",
                             "evidence_refs": only["evidence_refs"]}
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
         "evidence_refs": mm["evidence_refs"],
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
    # Stripped first. "   " is truthy, so it passed the exactly-one check
    # and then failed inside the adapter, where the broad handler below
    # turned a caller error into an envelope saying the geocoder was
    # unreachable — false outage telemetry, and advice to retry something
    # that will never work.
    address = address.strip()
    if bool(address) == bool(zip_code):
        raise InvalidQuery(
            "pass exactly one of `address` or `zip_code` — there is no "
            "precedence rule between them, and silently preferring one "
            "would hide a contradiction between what you typed and where "
            "it points")
    if address and ZIP_PATTERN.match(address):
        # A bare ZIP through the `address` parameter is still a ZIP, and
        # the locator answers one with a single centroid — the
        # one-to-many-collapsed-to-one failure the ZIP path exists to
        # prevent. Routing rather than refusing, because the caller asked
        # a question this tool can answer correctly.
        return await _resolve_zip(ctx, b, address)
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
    # Set when the ambiguity check already placed the winning candidate.
    already_placed = None
    data: dict = {"address": address,
                  "geocode": {"source_ref": geo_ref,
                              "min_score": g.min_score,
                              "candidate_count": len(g.candidates)}}

    if not confident:
        # Below the declared threshold, or nothing at all. Both are the
        # same instruction to the caller — do not proceed on this — but
        # they are different facts, so they read differently.
        data["resolved"] = None
        # These are the records whose ambiguity the caller has to judge,
        # so they are material and name their evidence like any other.
        weak_refs = {
            c.record_id: b.add_evidence(
                source_ref=geo_ref, record_id=c.record_id,
                retrieved_at=g.retrieved_at,
                transformations=g.transformations,
                payload_hash=g.payload_hash())
            for c in g.candidates[:INLINE_RECORD_CAP]}
        data["candidates"] = [
            {**c.canonical(), "evidence_refs": [weak_refs[c.record_id]],
             "distinguisher":
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

    # Several candidates can clear the threshold, and the locator's own
    # ranking settles ties within one place — not between two places. An
    # underspecified address can return equally confident matches in
    # different localities, and taking [0] there picks a government the
    # caller never chose.
    #
    # Distance is the wrong test for that, which the first attempt at
    # this got wrong: the address-point and road-centerline elements
    # routinely return the SAME address tens of metres apart, and any
    # rounding fine enough to separate two localities also separates
    # those. What matters is whether the candidates land in different
    # GOVERNMENTS, so each distinct coordinate is placed and the results
    # compared. Bounded, because each placement is two more queries.
    if len(confident) > 1:
        seen: dict[tuple[float, float], GeocodeCandidate] = {}
        for cand in confident:
            seen.setdefault((round(cand.lon, 5), round(cand.lat, 5)), cand)
        all_distinct = list(seen.values())
        distinct = all_distinct[:MAX_GEOCODE_CONTAINMENT_CHECKS]
        unchecked = len(all_distinct) - len(distinct)
        # Gated on how many distinct places the locator returned, not on
        # how many this got around to placing. Gating on the checked
        # prefix meant a cap of one skipped the block outright and
        # resolved the first candidate — the defect, one level down.
        if len(all_distinct) > 1:
            placed = []
            boundary_ref: str | None = None
            for cand in distinct:
                cont = await resolve_point(ctx, b, cand.lon, cand.lat,
                                           reuse_source_ref=boundary_ref)
                boundary_ref = boundary_ref or cont.source_ref
                leaf = cont.leaf
                placed.append((cand, (leaf or {}).get("jurisdiction"), cont))
            # A candidate whose boundary queries FAILED has no leaf, which
            # is indistinguishable from a candidate that landed outside
            # every polygon — so an outage on one placement read as a
            # second, different government and turned into apparent
            # address ambiguity with execution=complete.
            placement_failures = [f for _, _, cont in placed
                                  for f in cont.failures]
            # Unchecked candidates are not evidence of agreement. Four
            # matching prefixes and a fifth in another county reads
            # identically to five matching ones from here, so the cap
            # forces the same answer disagreement would.
            if placement_failures:
                data["resolved"] = None
                data["candidates"] = []
                data["note"] = (
                    "The address geocoded, but the boundary source failed "
                    "while placing one of the equally confident matches. "
                    "Which government this address is in is unknown — not "
                    "ambiguous. Retry rather than choosing between the "
                    "matches below.")
                return b.build(data, Coverage(
                    registry=registry_dim,
                    execution=ExecutionCoverage.partial,
                    pagination=PaginationCoverage.complete,
                    result=ResultCoverage.hit,
                    jurisdictions_searched=["va"],
                    source_failures=placement_failures))
            if len({j.id if j else None for _, j, _ in placed}) > 1 or unchecked:
                refs = {
                    cand.record_id: b.add_evidence(
                        source_ref=geo_ref, record_id=cand.record_id,
                        retrieved_at=g.retrieved_at,
                        transformations=g.transformations,
                        payload_hash=g.payload_hash())
                    for cand, _, _ in placed}
                data["resolved"] = None
                data["candidates"] = [
                    {**cand.canonical(),
                     "evidence_refs": [refs[cand.record_id]],
                     "jurisdiction": j.id if j else None,
                     "jurisdiction_name": j.name if j else None,
                     "distinguisher":
                         f"score {cand.score}, matched by "
                         f"{cand.matched_by or 'an unnamed locator element'}"
                         + (f", in {j.name}" if j
                            else ", in no mapped jurisdiction")}
                    for cand, j, _ in placed]
                data["note"] = (
                    f"{len(distinct)} matches scored at or above "
                    f"{g.min_score} and they are in different governments. "
                    if len({j.id if j else None for _, j, _ in placed}) > 1
                    else f"{len(all_distinct)} matches scored at or above "
                         f"{g.min_score}; the first {len(distinct)} were "
                         "placed and agree, and the rest were not checked. "
                    ) + (
                    "Picking one would choose a government the user did "
                    "not. Present them and let the user choose, or pass a "
                    "fuller address.")
                return b.build(data, Coverage(
                    registry=registry_dim,
                    execution=ExecutionCoverage.complete,
                    pagination=PaginationCoverage.complete,
                    result=ResultCoverage.hit,
                    jurisdictions_searched=["va"],
                    known_limitations=sorted(m.coverage.known_limitations)),
                    requires_user_choice=True)
            # They agree. `best` is `distinct[0]` — the locator's own
            # first result — and it was already placed in that loop.
            # Calling resolve_point again costs four more requests to a
            # government service, adds a duplicate provenance entry, and
            # gives an already-successful check a second chance to fail.
            already_placed = placed[0][2]

    best = confident[0]
    ev = b.add_evidence(source_ref=geo_ref, record_id=best.record_id,
                        retrieved_at=g.retrieved_at,
                        transformations=g.transformations,
                        payload_hash=g.payload_hash())
    data["geocode"].update({**best.canonical(), "evidence_refs": [ev]})
    if best.address_type.lower() in ("postal", "postalext", "locality"):
        # The locator fell back to a postal or place centroid, so its
        # answer is about an AREA, not the address. Resolving that
        # centroid returns the one government that happens to contain a
        # point in the middle of a ZIP, which is exactly what the ZIP
        # path refuses to do — so hand it to that path when there is a
        # ZIP to hand over, and withhold when there is not.
        if best.postal_code and ZIP_PATTERN.match(best.postal_code):
            zip_env = await _resolve_zip(ctx, b, best.postal_code)
            zip_env.data["geocode"] = data["geocode"]
            zip_env.data["note"] = (
                f"The locator had no match for {address!r} closer than the "
                f"{best.address_type} level, so this answers about ZIP "
                f"{best.postal_code} instead. "
                + str(zip_env.data.get("note") or ""))
            return zip_env
        data["resolved"] = None
        data["candidates"] = []
        data["note"] = (
            f"The locator matched only at the {best.address_type} level — "
            "a centroid for a whole postal or place area, not this "
            "address. Resolving that centroid would name the one "
            "government containing the middle of an area that may cross "
            "several. Pass a fuller street address.")
        return b.build(data, Coverage(
            registry=registry_dim, execution=ExecutionCoverage.complete,
            pagination=PaginationCoverage.complete,
            result=ResultCoverage.hit, jurisdictions_searched=["va"],
            known_limitations=sorted(m.coverage.known_limitations)),
            requires_user_choice=True)

    # A geocode is never a resolution on its own: the point goes through
    # the same point-in-polygon path registry.resolve_jurisdiction uses,
    # and the government that owns the polygon is the answer.
    c = already_placed if already_placed is not None \
        else await resolve_point(ctx, b, best.lon, best.lat)
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

    if c.narrowest_unknown:
        data["resolved"] = None
        data["candidates"] = []
        data["note"] = (
            "The address geocoded, but the town boundary layer could not "
            "be reached, so the narrowest government at that coordinate is "
            "unknown. A county polygon was found; the address may sit in "
            "an incorporated town inside it, and naming the county would "
            "be a plausible wrong answer. The coordinate is in `geocode` "
            "and can be retried.")
        return b.build(data, Coverage(
            registry=registry_dim, execution=ExecutionCoverage.partial,
            pagination=PaginationCoverage.complete,
            result=ResultCoverage.hit,
            jurisdictions_searched=["va"], source_failures=c.failures))

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
                            "basis": "geocode_then_point_in_polygon",
                            # The geocode evidence AND the boundary
                            # polygons: this answer rests on both steps.
                            "evidence_refs": [ev] + c.evidence_refs}
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


# --- buildings (GitHub issue #6) -------------------------------------------

# A building query's default reach. Small enough that a residential point
# returns the house and its neighbours rather than a city block, large
# enough that a coordinate taken off a map click still finds something.
BUILDING_RADIUS_M = 50.0


def _web_mercator_area_to_ground(area: float | None,
                                 latitude: float) -> float | None:
    """Web Mercator inflates area by sec squared of the latitude.

    The publisher's Shape__Area is computed in the layer's own projection
    (EPSG:3857, `geometryProperties.units: esriMeters`), where a square
    metre at 38 degrees north is about 1.6 real square metres. Dividing by
    the scale factor recovers an approximate ground area; it is an
    approximation because the factor varies across a footprint, which at
    building scale is far below the layer's own accuracy.
    """
    import math
    if area is None:
        return None
    scale = 1.0 / math.cos(math.radians(latitude))
    return round(area / (scale * scale), 1)


async def find_buildings(ctx: RuntimeContext, jurisdiction: str,
                         lon: float | None = None, lat: float | None = None,
                         pin: str = "",
                         radius_meters: float = BUILDING_RADIUS_M
                         ) -> Envelope:
    b = _builder(ctx, "geo.find_buildings")
    if (lon is None) != (lat is None):
        raise InvalidQuery("a point needs both lon and lat")
    if bool(pin) == (lon is not None and lat is not None):
        raise InvalidQuery("pass exactly one of `pin` or a lon/lat point")

    frame = _resolve_frame(ctx, b, jurisdiction)
    if frame.early is not None:
        return frame.early
    stack = frame.stack or []

    selected = ctx.sources.select("building.lookup", stack)
    registry_dim, gaps = selection_coverage(ctx.sources, "building.lookup",
                                            stack, selected)
    parcel_geometry: dict | None = None
    parcel_note: str | None = None
    parcel_evidence_ref: str | None = None
    any_parcel_answered = False
    failures = []
    if pin:
        # Composing with the parcel sources rather than duplicating them:
        # "what is built on this parcel" is a question about a polygon
        # somebody else publishes.
        parcels = ctx.sources.select("parcel.lookup", stack)
        for pm in parcels:
            try:
                pq = await ctx.arcgis.query(
                    pm, "parcels",
                    where_equals=_scoped_where(ctx, pm, "parcels", stack,
                                               {"pin": pin}),
                    return_geometry=True)
            except CommonwealthError as err:
                failures.append(failure(pm.id, err.code, str(err)))
                continue
            # Registered whether or not it matched. A source that answered
            # "no such PIN" was contacted, and its identity and freshness
            # belong in the envelope — an empty answer with empty
            # provenance hides which sources were even asked.
            any_parcel_answered = True
            parcel_ref = _source_entry(b, pm, pq)
            if pq.records:
                parcel_geometry = dict(pq.records[0].geometry or {})
                parcel_geometry.setdefault("spatialReference", {"wkid": 4326})
                # The parcel query is a consulted source: its polygon is
                # what every building below rests on, and with more than
                # one parcel source selectable a caller cannot otherwise
                # tell which one drew the boundary. Same discipline
                # find_zoning already applies to its parcel step.
                parcel_ref = _source_entry(b, pm, pq)
                parcel_evidence_ref = b.add_evidence(
                    source_ref=parcel_ref,
                    record_id=pq.records[0].record_id,
                    retrieved_at=pq.retrieved_at,
                    transformations=pq.transformations,
                    payload_hash=pq.payload_hash())
                if len(pq.records) > 1:
                    parcel_note = (
                        f"PIN {pin!r} matched {len(pq.records)} parcel "
                        "polygons in " + pm.id + "; buildings are reported "
                        "for the first. The others are not searched.")
                break
        if parcel_geometry is None:
            # An outage is not a miss. When every parcel source raised,
            # nothing was searched, and reporting "no parcel with that
            # PIN" would turn a service being down into a fact about the
            # ground — the distinction this envelope exists to keep.
            all_failed = bool(failures) and not any_parcel_answered
            return b.build(
                {"results": [],
                 "note": ("Every registered parcel source failed, so no "
                          "parcel geometry could be fetched and no "
                          "building search ran. This is an outage, not a "
                          "statement about this PIN or this ground."
                          if all_failed else
                          f"No parcel with PIN {pin!r} was found, so there "
                          "is no polygon to look for buildings on. That is "
                          "a parcel-lookup miss, not a statement that the "
                          "ground is unbuilt.")},
                Coverage(registry=registry_dim,
                         execution=(ExecutionCoverage.failed if all_failed
                                    else ExecutionCoverage.partial if failures
                                    else ExecutionCoverage.complete),
                         pagination=PaginationCoverage.complete,
                         result=ResultCoverage.empty,
                         jurisdictions_searched=stack,
                         jurisdictions_unavailable=gaps,
                         source_failures=failures))

    blocks: list[dict] = []
    queries: list[ArcGISQueryResult] = []
    for m in selected:
        try:
            if parcel_geometry is not None:
                q = await ctx.arcgis.query(m, "buildings",
                                           intersect_geometry=parcel_geometry)
                q.transformations.append("parcel_geometry_intersection")
            else:
                # Scoped like every other point path. The buffer reaches
                # `radius_meters`, so a point near a locality line returns
                # the neighbour's footprints while the envelope reports
                # only the jurisdiction that was asked for.
                q = await ctx.arcgis.query(
                    m, "buildings",
                    where_equals=_scoped_where(ctx, m, "buildings", stack,
                                               {}) or None,
                    geometry_point=(lon, lat),
                    distance_meters=radius_meters)
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        queries.append(q)
        # The latitude the area conversion is computed at. A point query
        # has one; a parcel query uses the parcel's own first vertex,
        # which is within metres of every building on it. Declared on the
        # query BEFORE the block is built, because evidence entries copy
        # the transformation list as it stands when they are created.
        ref_lat = lat if lat is not None else _first_vertex_lat(
            parcel_geometry)
        if ref_lat is not None:
            q.transformations.append(
                f"area:web_mercator_to_ground(lat={round(ref_lat, 4)})")
        block = _records_block(b, _source_entry(b, m, q), q, m)
        if parcel_geometry is None:
            note = _widened_note(ctx, m, "buildings", stack)
            if note:
                block["widened_scope"] = note
        for row in block["records"]:
            row["record_updated_at"] = _epoch_ms_to_iso(
                row.pop("last_update", None))
            raw_area = row.get("footprint_area_web_mercator_sq_m")
            if ref_lat is not None:
                row["footprint_area_sq_m_approx"] = \
                    _web_mercator_area_to_ground(raw_area, ref_lat)
            row["area_note"] = (
                "footprint_area_web_mercator_sq_m is the publisher's own "
                "value in EPSG:3857, where area is inflated by about 1.6x "
                "at Virginia's latitudes. The _approx field divides that "
                "out using this query's latitude." if ref_lat is not None
                else "footprint_area_web_mercator_sq_m is the publisher's "
                     "own value in EPSG:3857 and is NOT ground area; no "
                     "latitude was available to convert it.")
        if parcel_evidence_ref is not None:
            block["parcel_evidence_ref"] = parcel_evidence_ref
            for row in block["records"]:
                row["evidence_refs"] = (list(row["evidence_refs"])
                                        + [parcel_evidence_ref])
        blocks.append(block)

    if any(blk["record_count"] for blk in blocks):
        b.warn(WarningCode.screening_only,
               "Building footprints are a derived screening layer. A "
               "missing footprint is not evidence of vacant land, and "
               "height, storey, and class fields are sparse — null means "
               "the publisher has no value, not that the building has "
               "none.")

    execution = (ExecutionCoverage.complete if not failures
                 else ExecutionCoverage.failed if not blocks
                 else ExecutionCoverage.partial)
    total = sum(blk["record_count"] for blk in blocks)
    data: dict = {"results": blocks}
    if parcel_note:
        data["parcel_note"] = parcel_note
    return b.build(data, Coverage(
        registry=registry_dim, execution=execution,
        pagination=_pagination_dim(queries), result=result_dim(total),
        jurisdictions_searched=stack if selected else [],
        jurisdictions_unavailable=gaps, source_failures=failures,
        known_limitations=sorted({lim for m in selected
                                  for lim in m.coverage.known_limitations})))


def _first_vertex_lat(geometry: dict | None) -> float | None:
    rings = (geometry or {}).get("rings") or []
    for ring in rings:
        for point in ring:
            if len(point) >= 2:
                return float(point[1])
    return None


GEO_TOOLS.register(ToolSpec(
    name="geo.find_buildings",
    description=(
        "Find building footprints at a lon/lat point (with a radius) or on "
        "a parcel PIN in a Virginia jurisdiction. Answers 'is this ground "
        "built on, and how much of it'. An empty result is NOT evidence "
        "of vacant land — this is a derived layer whose coverage varies by "
        "locality. Height, storey, and class fields are frequently null, "
        "which means the publisher has no value. Footprint area is "
        "published in Web Mercator, where area is inflated about 1.6x at "
        "Virginia's latitudes; both the publisher's number and a converted "
        "approximation are returned, each labelled. A dense urban query "
        "truncates — narrow the radius rather than reading a short list "
        "as the whole answer."),
    toolset="default", contract_version="1", fn=find_buildings))


# --- landmarks (GitHub issue #7) -------------------------------------------

LANDMARK_RADIUS_M = 1000.0


async def find_landmarks(ctx: RuntimeContext, jurisdiction: str,
                         name: str = "", place_type: str = "",
                         lon: float | None = None, lat: float | None = None,
                         radius_meters: float = LANDMARK_RADIUS_M
                         ) -> Envelope:
    b = _builder(ctx, "geo.find_landmarks")
    if (lon is None) != (lat is None):
        raise InvalidQuery("a point needs both lon and lat")
    if not (name or place_type or lon is not None):
        raise InvalidQuery(
            "pass at least one of `name`, `place_type`, or a lon/lat point "
            "— an unbounded query would return every landmark in the "
            "jurisdiction")

    frame = _resolve_frame(ctx, b, jurisdiction)
    if frame.early is not None:
        return frame.early
    stack = frame.stack or []

    selected = ctx.sources.select("landmark.lookup", stack)
    registry_dim, gaps = selection_coverage(ctx.sources, "landmark.lookup",
                                            stack, selected)
    blocks: list[dict] = []
    failures = []
    queries: list[ArcGISQueryResult] = []
    for m in selected:
        equals = _scoped_where(ctx, m, "landmarks", stack, {})
        scope_note = _widened_note(ctx, m, "landmarks", stack)
        if place_type:
            equals = {**equals, "place_type": place_type}
        try:
            q = await ctx.arcgis.query(
                m, "landmarks",
                where_equals=equals or None,
                where_prefix={"name": name} if name else None,
                geometry_point=(lon, lat) if lon is not None else None,
                distance_meters=(radius_meters if lon is not None else None))
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        queries.append(q)
        block = _records_block(b, _source_entry(b, m, q), q, m)
        if scope_note:
            block["widened_scope"] = scope_note
        for row in block["records"]:
            checked = _epoch_ms_to_iso(row.pop("last_checked", None))
            row["record_checked_at"] = checked
            if checked is None:
                # Inheriting the layer's date here would say the record was
                # verified when nobody has verified it.
                row["record_checked_note"] = (
                    "The publisher has no verification date for this "
                    "record. That is not the same as verified recently.")
            row["authority_note"] = (
                f"This record came from {row.get('source_organization') or 'an unnamed source'}"
                f" ({row.get('source_type') or 'type not stated'}), not from "
                "the layer's publisher. That organisation is the authority "
                "for it. `postal_city` is a postal city, not the "
                "government; read `locality` / `fips` for that.")
            if row.get("url"):
                row["url_note"] = ("Returned as data. Nothing in "
                                   "Commonwealth fetches a link found "
                                   "inside a record.")
        blocks.append(block)

    if any(blk["record_count"] for blk in blocks):
        b.warn(WarningCode.screening_only,
               "This is a curated convenience layer, not an inventory. A "
               "place missing from it may simply never have been added, "
               "and each record's authority is the organisation named in "
               "`source_organization`, not the layer's publisher.")

    execution = (ExecutionCoverage.complete if not failures
                 else ExecutionCoverage.failed if not blocks
                 else ExecutionCoverage.partial)
    total = sum(blk["record_count"] for blk in blocks)
    return b.build({"results": blocks}, Coverage(
        registry=registry_dim, execution=execution,
        pagination=_pagination_dim(queries), result=result_dim(total),
        jurisdictions_searched=stack if selected else [],
        jurisdictions_unavailable=gaps, source_failures=failures,
        known_limitations=sorted({lim for m in selected
                                  for lim in m.coverage.known_limitations})))


GEO_TOOLS.register(ToolSpec(
    name="geo.find_landmarks",
    description=(
        "Find named public places in a Virginia jurisdiction — schools, "
        "libraries, fire stations, DMV offices, state parks — by name "
        "prefix, by the publisher's own place_type vocabulary, or near a "
        "lon/lat point. NOT an inventory: a place missing from this layer "
        "may simply never have been added, so an empty result never means "
        "there is no school there. Each record names the organisation it "
        "came from, and that organisation is its authority, not the map "
        "publisher. Record URLs are returned as data and are never "
        "fetched. Pass at least one filter."),
    toolset="spatial", contract_version="1", fn=find_landmarks))


# --- roads (GitHub issue #5) -----------------------------------------------

ROAD_RADIUS_M = 100.0


async def find_roads(ctx: RuntimeContext, jurisdiction: str,
                     street_name: str = "", lon: float | None = None,
                     lat: float | None = None,
                     radius_meters: float = ROAD_RADIUS_M) -> Envelope:
    b = _builder(ctx, "geo.find_roads")
    if (lon is None) != (lat is None):
        raise InvalidQuery("a point needs both lon and lat")
    if bool(street_name) == (lon is not None and lat is not None):
        raise InvalidQuery(
            "pass exactly one of `street_name` or a lon/lat point")

    frame = _resolve_frame(ctx, b, jurisdiction)
    if frame.early is not None:
        return frame.early
    stack = frame.stack or []

    selected = ctx.sources.select("road.lookup", stack)
    registry_dim, gaps = selection_coverage(ctx.sources, "road.lookup",
                                            stack, selected)
    blocks: list[dict] = []
    failures = []
    queries: list[ArcGISQueryResult] = []
    unscoped: list[str] = []
    unscoped_by_geometry: list[str] = []
    widened: dict[str, str] = {}
    for m in selected:
        layer_key = _road_layer(ctx, m)
        scope = _jurisdiction_scope(ctx, m, layer_key, stack)
        by_point = lon is not None
        if by_point and scope.mode == "jurisdiction_names":
            # VDOT leaves RTE_JURIS_PROPER_NM null on about 6,500 routes
            # — the interstates and frontage roads that span localities —
            # and its own manifest says those are meant to be found by
            # proximity. ANDing a name equality onto a geometry filter
            # drops exactly those, so a query beside an interstate would
            # not return the interstate. The point already bounds the
            # answer; the name filter has nothing left to add.
            scope = _Scope(narrowed_to=stack[0] if stack else None)
            unscoped_by_geometry.append(m.id)
        if scope.groups is None and not by_point:
            unscoped.append(m.id)
        note = scope.note(ctx, stack[0])
        if note:
            widened[m.id] = note
        try:
            q = await ctx.arcgis.query(
                m, layer_key,
                where_prefix={"street_name": street_name}
                if street_name else None,
                where_any_of=scope.groups,
                geometry_point=(lon, lat) if lon is not None else None,
                distance_meters=(radius_meters if lon is not None else None))
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        queries.append(q)
        block = _records_block(b, _source_entry(b, m, q), q, m)
        block["layer"] = layer_key
        for row in block["records"]:
            if "last_update" in row:
                row["record_updated_at"] = _epoch_ms_to_iso(
                    row.pop("last_update"))
            if "geometry_effective_date" in row:
                row["geometry_effective_date"] = _epoch_ms_to_iso(
                    row.get("geometry_effective_date"))
        blocks.append(block)

    execution = (ExecutionCoverage.complete if not failures
                 else ExecutionCoverage.failed if not blocks
                 else ExecutionCoverage.partial)
    total = sum(blk["record_count"] for blk in blocks)
    data: dict = {"results": blocks}
    comparison = _compare(blocks, "street_name")
    if comparison:
        if comparison["agreement"] is False:
            # Only when they actually differ. `agreement: None` means one
            # source returned nothing, which is a different fact and
            # carries its own note — overwriting it would collapse "these
            # two disagree" and "only one of them has this road" into one
            # sentence.
            comparison["note"] = (
                "These two publishers describe the same roads differently "
                "by design: one is the operating agency's route inventory "
                "with its own identifiers, the other aggregates local "
                "centerline submissions. A difference here is usually a "
                "difference in how the road is named or modelled, not an "
                "error in either. Neither has been reconciled away.")
        data["comparison"] = comparison
    if unscoped:
        data["unscoped_sources"] = {
            "source_ids": unscoped,
            "note": "These sources could not be narrowed to the requested "
                    "jurisdiction — the layer either declares no "
                    "jurisdiction key or the jurisdiction supplies no "
                    "value for it — so their results are statewide for "
                    "the query. Read them accordingly."}
    if unscoped_by_geometry:
        data["geometry_scoped_sources"] = {
            "source_ids": unscoped_by_geometry,
            "note": "These sources key jurisdiction on a NAME, and some of "
                    "their records leave it blank — the routes that span "
                    "localities. The point and its radius bound this "
                    "answer instead, so a road with no jurisdiction "
                    "recorded is still found."}
    if widened:
        # A town has no FIPS of its own, so a layer keyed on FIPS reaches
        # its county and no further. Saying so is the difference between
        # a county's roads labelled "Vienna" and a county's roads that
        # say they are the county's.
        data["widened_scope"] = widened
    if total:
        b.warn(WarningCode.screening_only,
               "Road geometry is a centerline or a linear reference, not "
               "a right-of-way boundary, and neither publisher offers it "
               "as a survey. The two sources model roads differently and "
               "both answers are shown unreconciled.")
    return b.build(data, Coverage(
        registry=registry_dim, execution=execution,
        pagination=_pagination_dim(queries), result=result_dim(total),
        jurisdictions_searched=stack if selected else [],
        jurisdictions_unavailable=gaps, source_failures=failures,
        known_limitations=sorted({lim for m in selected
                                  for lim in m.coverage.known_limitations})))


def _road_layer(ctx: RuntimeContext, m: SourceManifest) -> str:
    """The layer a road source is queried through.

    VGIN's centerline service publishes four layers of which only one is
    the complete feature class; the others are cartographic subsets and a
    scale duplicate, registered for their health floors. Picking by
    convention over the manifest's own layer keys keeps that decision in
    one place."""
    layers = set(ctx.arcgis.layer_keys(m))
    for preferred in ("centerlines", "routes"):
        if preferred in layers:
            return preferred
    raise InvalidQuery(
        f"{m.id} answers road.lookup but declares no 'centerlines' or "
        f"'routes' layer; declared: {sorted(layers)}")


GEO_TOOLS.register(ToolSpec(
    name="geo.find_roads",
    description=(
        "Find road segments and routes in a Virginia jurisdiction, by "
        "street-name prefix or near a lon/lat point. TWO official sources "
        "answer this and they are expected to disagree: VDOT's route "
        "inventory is a linear-referencing model with its own route names "
        "and measures, VGIN's centerlines are an aggregation of local "
        "submissions with segment-level detail. Both are returned "
        "unreconciled and the comparison block says whether their names "
        "agree — a difference is usually a difference in how the road is "
        "modelled, not an error. Centerlines are not right-of-way "
        "boundaries. A road along a locality line belongs to both "
        "localities in the results."),
    toolset="spatial", contract_version="1", fn=find_roads))


# --- environmental sites (GitHub issue #8) ---------------------------------

# One mile, the distance a property screening conventionally asks about.
ENVIRONMENTAL_RADIUS_M = 1609.0


async def find_environmental_sites(
        ctx: RuntimeContext, jurisdiction: str, lon: float | None = None,
        lat: float | None = None,
        radius_meters: float = ENVIRONMENTAL_RADIUS_M) -> Envelope:
    b = _builder(ctx, "geo.find_environmental_sites")
    if lon is None or lat is None:
        # The registered layer carries no locality field, so a
        # jurisdiction-only query would return every station in Virginia
        # under a heading that says one county. Requiring the point is the
        # difference between a scoped answer and a mislabelled one.
        raise InvalidQuery(
            "a lon/lat point is required: the registered environmental "
            "source is organised by watershed, not by jurisdiction, so "
            "there is no jurisdiction filter to apply and a "
            "jurisdiction-only query would return the whole state")

    frame = _resolve_frame(ctx, b, jurisdiction)
    if frame.early is not None:
        return frame.early
    stack = frame.stack or []

    selected = ctx.sources.select("environmental_site.lookup", stack)
    registry_dim, gaps = selection_coverage(
        ctx.sources, "environmental_site.lookup", stack, selected)
    blocks: list[dict] = []
    failures = []
    queries: list[ArcGISQueryResult] = []
    for m in selected:
        try:
            q = await ctx.arcgis.query(m, "stations",
                                       geometry_point=(lon, lat),
                                       distance_meters=radius_meters)
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        queries.append(q)
        block = _records_block(b, _source_entry(b, m, q), q, m)
        for row in block["records"]:
            for field in ("first_sample_date", "last_sample_date",
                          "last_benthic_date"):
                row[field] = _epoch_ms_to_iso(row.get(field))
            row["record_note"] = (
                "A monitoring station on record. It says this spot is or "
                "was sampled; it says nothing about what was found, "
                "whether anything is contaminated, or whether the ground "
                "is suitable for any use. Check last_sample_date — "
                "historic stations are included.")
        block["search_note"] = (
            f"Stations within {radius_meters:.0f} m of the point. This "
            "source has no locality field, so the search is geographic "
            "and results may sit in a neighbouring jurisdiction.")
        blocks.append(block)

    execution = (ExecutionCoverage.complete if not failures
                 else ExecutionCoverage.failed if not blocks
                 else ExecutionCoverage.partial)
    total = sum(blk["record_count"] for blk in blocks)
    # The disclaimer rides on every answer, including the empty one — an
    # empty environmental result is the one most likely to be read as
    # "nothing here", which is exactly what it does not mean.
    b.warn(WarningCode.screening_only,
           "This is NOT a complete inventory of environmental sites and "
           "NOT a determination that any site is safe, contaminated, or "
           "suitable for a given use. It is one agency's water-quality "
           "monitoring network. An empty result means no monitoring "
           "station of that kind is on record near this point, and "
           "nothing more than that.")
    return b.build(
        {"point": {"lon": lon, "lat": lat}, "results": blocks},
        Coverage(registry=registry_dim, execution=execution,
                 pagination=_pagination_dim(queries),
                 result=result_dim(total),
                 jurisdictions_searched=stack if selected else [],
                 jurisdictions_unavailable=gaps, source_failures=failures,
                 known_limitations=sorted(
                     {lim for m in selected
                      for lim in m.coverage.known_limitations})))


GEO_TOOLS.register(ToolSpec(
    name="geo.find_environmental_sites",
    description=(
        "Find the environmental monitoring stations a Virginia agency has "
        "on record near a lon/lat point. READ THE LIMITS BEFORE USING "
        "THIS: it is NOT a complete inventory of environmental sites, and "
        "it is NOT a determination that any site is safe, contaminated, "
        "or suitable for a given use. What is registered today is DEQ's "
        "water-quality monitoring network — air, waste, and land "
        "programmes are not in it. A station on record means that spot is "
        "or was sampled and nothing more; historic stations are included, "
        "so read last_sample_date. An empty result means no station of "
        "that kind is on record near the point, never that the ground is "
        "clean. Say all of this to the user; do not summarise it away. "
        "A point is required — this source has no locality field."),
    toolset="default", contract_version="1", fn=find_environmental_sites))
