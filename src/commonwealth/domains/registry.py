"""Registry/discovery tools: jurisdiction resolution and source discovery.

Contracts: design/domain-servers.md § 2, design/jurisdiction-resolution.md.
"""
from __future__ import annotations

import re

from ..core.assemble import (EnvelopeBuilder, failure, result_dim,
                             selection_coverage)
from ..core.registry import SourceManifest
from ..core.envelope import (AccessPath, AuthorityLevel, Coverage, Envelope,
                             ExecutionCoverage, PaginationCoverage,
                             RegistryCoverage, ResultCoverage, WarningCode)
from ..core.errors import CommonwealthError, InvalidQuery
from ..core.toolreg import ToolRegistry, ToolSpec
from ..runtime import PROJECT_SOURCE, RuntimeContext

REGISTRY_TOOLS = ToolRegistry(package="registry")

# Point-in-polygon runs against the statewide boundary source, so the
# selection stack is the state itself — the whole point is that the
# jurisdiction is not yet known.
_STATEWIDE_STACK = ["va"]

# How close to another jurisdiction's boundary a point may sit before the
# answer is flagged as boundary-sensitive. This is a COMMONWEALTH-CHOSEN
# screening tolerance, not a publisher-stated accuracy figure: VGIN states
# none for the administrative-boundary layer, and inventing one would be a
# guess dressed as a measurement. The buffered query runs against the
# layer's true geometry, so the number means what it says; what it cannot
# tell you is how far the published line sits from the legal line.
BOUNDARY_PROXIMITY_METERS = 50


def _builder(ctx: RuntimeContext, tool: str,
             contract_version: str = "1") -> EnvelopeBuilder:
    return EnvelopeBuilder(server=ctx.server_name,
                           server_version=ctx.server_version, tool=tool,
                           contract_version=contract_version,
                           registry_revision=ctx.sources.revision,
                           adapters=ctx.adapters)


def _project_source(b: EnvelopeBuilder, ctx: RuntimeContext) -> str:
    from ..core.envelope import utc_now_iso
    # Project-authored data: its vintage is the repo state, so the
    # missing-publisher-date warning meant for government layers stays off.
    return b.add_source(**PROJECT_SOURCE, jurisdiction="va",
                        authority_level=AuthorityLevel.official_derived,
                        access_path=AccessPath.index,
                        source_updated_at=None,
                        retrieved_at=utc_now_iso(), cache_age_seconds=0,
                        warn_on_missing_freshness=False)


async def _resolve_by_point(ctx: RuntimeContext, b: EnvelopeBuilder,
                            lon: float, lat: float) -> Envelope:
    """Point-in-polygon against the registered boundary source
    (design/jurisdiction-resolution.md § 2). Two layers are consulted
    because Virginia stacks governments: an incorporated town and its
    parent county both contain the same ground, and 'whose zoning' and
    'whose schools' have different answers there."""
    from ..core.envelope import utc_now_iso

    selected = ctx.sources.select("boundary.lookup", _STATEWIDE_STACK)
    registry_dim, gaps = selection_coverage(
        ctx.sources, "boundary.lookup", _STATEWIDE_STACK, selected)
    if not selected:
        return b.build(
            {"resolved": None, "candidates": [],
             "note": "No boundary source is registered and active, so a "
                     "coordinate cannot be placed in a jurisdiction. This "
                     "is a Commonwealth coverage gap, not a statement "
                     "about the point."},
            Coverage(registry=registry_dim,
                     execution=ExecutionCoverage.complete,
                     pagination=PaginationCoverage.complete,
                     result=ResultCoverage.empty,
                     jurisdictions_unavailable=gaps))

    m = selected[0]
    failures = []
    hits: dict[str, list] = {"localities": [], "towns": []}
    near: dict[str, list] = {"localities": [], "towns": []}
    src_ref: str | None = None
    for layer in ("localities", "towns"):
        try:
            q = await ctx.arcgis.query(m, layer, geometry_point=(lon, lat))
            buffered = await ctx.arcgis.query(
                m, layer, geometry_point=(lon, lat),
                distance_meters=BOUNDARY_PROXIMITY_METERS)
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        if src_ref is None:
            src_ref = b.add_source(
                source_id=m.id, publisher=m.publisher.agency,
                system=m.adapter.type, dataset=m.name,
                jurisdiction=m.jurisdiction,
                authority_level=m.publisher.authority_level,
                access_path=AccessPath.cache if q.from_cache
                else AccessPath.live,
                source_updated_at=q.source_updated_at,
                retrieved_at=q.retrieved_at,
                cache_age_seconds=q.cache_age_seconds)
        for r in q.records:
            b.add_evidence(source_ref=src_ref, record_id=r.record_id,
                           retrieved_at=q.retrieved_at,
                           transformations=q.transformations,
                           payload_hash=q.payload_hash())
        hits[layer] = q.records
        near[layer] = buffered.records

    if failures and src_ref is None:
        return b.build(
            {"resolved": None, "candidates": [],
             "note": "The boundary source could not be reached, so this "
                     "point was not placed. That is an outage, not an "
                     "answer — do not read it as 'outside Virginia'."},
            Coverage(registry=registry_dim,
                     execution=ExecutionCoverage.failed,
                     pagination=PaginationCoverage.complete,
                     result=ResultCoverage.empty,
                     source_failures=failures))

    def identify(layer: str, rec) -> dict:
        """Map one boundary polygon back to the project's own table."""
        canon = rec.canonical
        if layer == "towns":
            raw = str(canon.get("place_fips") or "")
            state = ctx.jurisdictions.get("va")
            prefix = (state.fips if state else "51") or "51"
            bare = raw[len(prefix):] if raw.startswith(prefix) else raw
            j = ctx.jurisdictions.by_place_fips(bare)
        else:
            j = ctx.jurisdictions.by_fips(str(canon.get("fips") or ""))
        return {"source_name": canon.get("full_name"),
                "source_fips": canon.get("fips") or canon.get("place_fips"),
                "layer": layer, "jurisdiction": j}

    town = [identify("towns", r) for r in hits["towns"]]
    locality = [identify("localities", r) for r in hits["localities"]]

    if not town and not locality:
        return b.build(
            {"resolved": None, "candidates": [],
             "point": {"lon": lon, "lat": lat},
             "note": "No Virginia locality polygon contains this point. It "
                     "is outside the Commonwealth (or in water beyond the "
                     "mapped boundary). The source answered; it simply has "
                     "no polygon here."},
            Coverage(registry=registry_dim,
                     execution=ExecutionCoverage.complete,
                     pagination=PaginationCoverage.complete,
                     result=ResultCoverage.empty,
                     jurisdictions_searched=_STATEWIDE_STACK,
                     source_failures=failures,
                     known_limitations=sorted(m.coverage.known_limitations)))

    # The town is the narrowest government containing the point; the
    # locality is always reported alongside it, never replaced by it.
    leaf = (town or locality)[0]
    data: dict = {"point": {"lon": lon, "lat": lat}}
    layered: list[dict[str, str]] = []
    for entry in locality if town else []:
        j = entry["jurisdiction"]
        layered.append({"id": j.id if j else f"unmapped:{entry['source_fips']}",
                        "relationship": "containing-locality",
                        "name": entry["source_name"] or ""})

    resolved_j = leaf["jurisdiction"]
    if resolved_j is not None:
        for p in ctx.jurisdictions.parents_of(resolved_j):
            if not any(row.get("id") == p.id for row in layered):
                layered.append({"id": p.id,
                                "relationship": "parent-" + p.kind.value,
                                "name": p.name})
        data["resolved"] = {"id": resolved_j.id, "name": resolved_j.name,
                            "kind": resolved_j.kind.value,
                            "fips": resolved_j.fips,
                            "basis": "point_in_polygon"}
        data["candidates"] = []
    else:
        # The boundary source knows this government; Commonwealth's own
        # table does not carry it yet. Saying "unresolved" flatly would
        # throw away a real, sourced answer.
        data["resolved"] = None
        data["candidates"] = []
        data["unmapped_match"] = {
            "source_name": leaf["source_name"],
            "source_fips": leaf["source_fips"],
            "layer": leaf["layer"],
            "note": "The boundary source places this point in the "
                    "jurisdiction named here, but that jurisdiction is not "
                    "in Commonwealth's jurisdiction table yet, so it has no "
                    "va: id and no source routing. The place is real; the "
                    "gap is ours."}
    data["layered_authorities"] = layered

    # Straddle check: anything the buffered query reached that the exact
    # query did not is a different government within the tolerance.
    exact_ids = {r.record_id for layer in hits for r in hits[layer]}
    neighbours = sorted({
        str(r.canonical.get("full_name"))
        for layer in near for r in near[layer]
        if r.record_id not in exact_ids})
    if neighbours:
        b.warn(WarningCode.boundary_precision,
               f"This point is within {BOUNDARY_PROXIMITY_METERS} m of "
               f"{', '.join(neighbours)}. The published boundary is "
               "cartographic and the publisher disclaims survey use, so "
               "which side of the line this point falls on is not settled "
               "by this answer. Confirm with the locality before relying "
               "on it.", m.id)
        data["nearby_jurisdictions"] = neighbours

    return b.build(data, Coverage(
        registry=registry_dim,
        execution=(ExecutionCoverage.partial if failures
                   else ExecutionCoverage.complete),
        pagination=PaginationCoverage.complete,
        result=ResultCoverage.hit,
        jurisdictions_searched=_STATEWIDE_STACK,
        source_failures=failures,
        known_limitations=sorted(m.coverage.known_limitations)))


async def resolve_jurisdiction(ctx: RuntimeContext, query: str = "",
                               lon: float | None = None,
                               lat: float | None = None) -> Envelope:
    b = _builder(ctx, "registry.resolve_jurisdiction", contract_version="2")
    has_point = lon is not None or lat is not None
    # design/jurisdiction-resolution.md § 2: more than one input is an error
    # naming the conflict, never a silent precedence rule.
    if query and has_point:
        raise InvalidQuery(
            "pass either `query` or a lon/lat point, not both — there is no "
            "precedence rule between them, and silently preferring one "
            "would hide a contradiction between what you named and where "
            "you pointed")
    if has_point and (lon is None or lat is None):
        raise InvalidQuery("a point needs both lon and lat")
    if not query and not has_point:
        raise InvalidQuery("pass a name, FIPS code, va: id, or a lon/lat "
                           "point")
    if has_point:
        assert lon is not None and lat is not None
        return await _resolve_by_point(ctx, b, lon, lat)

    resolution = ctx.jurisdictions.resolve(query)
    src = _project_source(b, ctx)

    if resolution.resolved is not None:
        j = resolution.resolved
        from ..core.envelope import utc_now_iso
        b.add_evidence(source_ref=src, record_id=j.id,
                       retrieved_at=utc_now_iso(), transformations=[])
        data = {
            "resolved": {"id": j.id, "name": j.name, "kind": j.kind.value,
                         "fips": j.fips, "basis": resolution.basis},
            "layered_authorities": resolution.layered_authorities,
        }
        return b.build(data, Coverage(
            registry=RegistryCoverage.covered,
            execution=ExecutionCoverage.complete,
            pagination=PaginationCoverage.complete,
            result=ResultCoverage.hit))

    if resolution.candidates:
        data = {
            "resolved": None,
            "candidates": [c.model_dump() for c in resolution.candidates],
            "note": "Multiple Virginia jurisdictions match. Present the "
                    "candidates and their distinguishers to the user; do "
                    "not select one yourself.",
        }
        return b.build(data, Coverage(
            registry=RegistryCoverage.covered,
            execution=ExecutionCoverage.complete,
            pagination=PaginationCoverage.complete,
            result=ResultCoverage.hit), requires_user_choice=True)

    data = {"resolved": None, "candidates": [],
            "note": f"No Virginia jurisdiction matches {query!r} in the "
                    "table. The table covers the state, its counties and "
                    "independent cities in the pilot set, and pilot towns."}
    return b.build(data, Coverage(
        registry=RegistryCoverage.covered,
        execution=ExecutionCoverage.complete,
        pagination=PaginationCoverage.complete,
        result=ResultCoverage.empty))


def _search_terms(text: str) -> list[str]:
    """Split a query into lowercase word stems.

    Matching used to be a raw substring test over `name + id`, which broke
    both ways once the registry held more than a handful of manifests: a
    search for "road" matched "crossroads", and "Fairfax County parcels"
    matched nothing because no single field contains that whole string.
    """
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def _matches_terms(terms: list[str], m: SourceManifest) -> bool:
    """True when every query term matches a word in the manifest's name,
    id, jurisdiction, or publisher.

    Every term has to match (AND), so extra words narrow rather than widen.
    A term matches a word by prefix, so "parcel" finds "parcels" without
    "road" finding "crossroads".
    """
    haystack = " ".join([
        m.name, m.id, m.jurisdiction or "", m.publisher.agency or "",
        " ".join(sorted(m.capability_ids())),
    ]).lower()
    words = [w for w in re.split(r"[^a-z0-9]+", haystack) if w]
    return all(any(w.startswith(term) for w in words) for term in terms)


async def search_sources(ctx: RuntimeContext, text: str = "",
                         jurisdiction: str = "",
                         capability: str = "") -> Envelope:
    b = _builder(ctx, "registry.search_sources")
    if capability and capability not in ctx.sources.capability_vocab:
        raise InvalidQuery(f"capability {capability!r} is not in the "
                           f"vocabulary; known: "
                           f"{sorted(ctx.sources.capability_vocab)}")
    hits = []
    terms = _search_terms(text)
    for m in ctx.sources.manifests.values():
        if terms and not _matches_terms(terms, m):
            continue
        if jurisdiction and m.jurisdiction != jurisdiction:
            continue
        if capability and capability not in m.capability_ids():
            continue
        hits.append({
            "id": m.id, "name": m.name, "jurisdiction": m.jurisdiction,
            "capabilities": sorted(m.capability_ids()),
            "authority_level": m.publisher.authority_level.value,
            "declared_state": m.lifecycle.declared_state.value,
            "operational_state": ctx.sources.operational(m.id).value,
        })
    hits.sort(key=lambda h: h["id"])
    src = _project_source(b, ctx)
    from ..core.envelope import utc_now_iso
    for h in hits:
        b.add_evidence(source_ref=src, record_id=h["id"],
                       retrieved_at=utc_now_iso(), transformations=[])
    return b.build(
        {"sources": hits, "record_count": len(hits)},
        Coverage(registry=RegistryCoverage.covered,
                 execution=ExecutionCoverage.complete,
                 pagination=PaginationCoverage.complete,
                 result=result_dim(len(hits))))


async def describe_source(ctx: RuntimeContext, source_id: str) -> Envelope:
    b = _builder(ctx, "registry.describe_source")
    m = ctx.sources.get(source_id)
    src = _project_source(b, ctx)
    if m is None:
        return b.build(
            {"source": None,
             "note": f"No source {source_id!r} in the registry. "
                     "registry.search_sources lists what exists."},
            Coverage(registry=RegistryCoverage.covered,
                     execution=ExecutionCoverage.complete,
                     pagination=PaginationCoverage.complete,
                     result=ResultCoverage.empty))
    from ..core.envelope import utc_now_iso
    b.add_evidence(source_ref=src, record_id=m.id,
                   retrieved_at=utc_now_iso(), transformations=[])
    data = {"source": {
        "id": m.id, "name": m.name, "jurisdiction": m.jurisdiction,
        "publisher": m.publisher.agency,
        "authority_level": m.publisher.authority_level.value,
        "capabilities": sorted(m.capability_ids()),
        "terms_url": m.access.terms_url,
        "terms_notes": m.access.terms_notes,
        "data_classification": m.access.data_classification.value,
        "known_limitations": m.coverage.known_limitations,
        "authority_notes": m.authority_notes,
        "declared_state": m.lifecycle.declared_state.value,
        "last_verified": m.lifecycle.last_verified,
    }}
    return b.build(data, Coverage(
        registry=RegistryCoverage.covered,
        execution=ExecutionCoverage.complete,
        pagination=PaginationCoverage.complete,
        result=ResultCoverage.hit))


async def source_status(ctx: RuntimeContext, source_id: str = "") -> Envelope:
    b = _builder(ctx, "registry.source_status")
    ids = [source_id] if source_id else sorted(ctx.sources.manifests)
    rows = []
    for sid in ids:
        m = ctx.sources.get(sid)
        if m is None:
            continue
        rows.append({"id": sid,
                     "declared_state": m.lifecycle.declared_state.value,
                     "operational_state": ctx.sources.operational(sid).value,
                     "last_verified": m.lifecycle.last_verified})
    src = _project_source(b, ctx)
    from ..core.envelope import utc_now_iso
    for r in rows:
        b.add_evidence(source_ref=src, record_id=r["id"],
                       retrieved_at=utc_now_iso(), transformations=[])
    return b.build(
        {"sources": rows, "record_count": len(rows),
         "note": "operational_state comes from runtime probes; 'unknown' "
                 "means no probe has run in this process."},
        Coverage(registry=RegistryCoverage.covered,
                 execution=ExecutionCoverage.complete,
                 pagination=PaginationCoverage.complete,
                 result=result_dim(len(rows))))


REGISTRY_TOOLS.register(ToolSpec(
    name="registry.resolve_jurisdiction",
    description=(
        "Resolve a Virginia jurisdiction from a name, alias, or FIPS code, "
        "or from a lon/lat point by point-in-polygon against official "
        "boundaries. Use FIRST whenever a place is named or a coordinate is "
        "given: Virginia has independent cities that are not inside the "
        "counties sharing their names (Fairfax City is not in Fairfax "
        "County), and towns that sit inside a county so BOTH governments "
        "apply — read layered_authorities, do not assume the resolved leaf "
        "answers everything. Pass `query` OR lon/lat, never both. If the "
        "result carries candidates with requires_user_choice, present them "
        "to the user and never pick one yourself. Not for street addresses "
        "yet (no geocoding in this release)."),
    toolset="discovery-min", contract_version="2", fn=resolve_jurisdiction))
REGISTRY_TOOLS.register(ToolSpec(
    name="registry.search_sources",
    description=(
        "Search the Government Source Registry: which registered public "
        "systems cover a capability or jurisdiction, with authority level "
        "and current state. Use to answer 'what does Commonwealth cover?' "
        "before assuming coverage. Not a data query tool — use the geo.* "
        "tools for actual records."),
    toolset="discovery", contract_version="1", fn=search_sources))
REGISTRY_TOOLS.register(ToolSpec(
    name="registry.describe_source",
    description=(
        "Full registry entry for one source id: publisher, authority, "
        "terms, limitations. Use when the user asks where an answer came "
        "from or what a source's caveats are."),
    toolset="discovery", contract_version="1", fn=describe_source))
REGISTRY_TOOLS.register(ToolSpec(
    name="registry.source_status",
    description=(
        "Declared and operational state for registered sources. Use when a "
        "query reported a source failure and you need to say whether the "
        "source is known-down."),
    toolset="discovery", contract_version="1", fn=source_status))
