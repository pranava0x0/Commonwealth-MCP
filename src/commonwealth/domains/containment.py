"""Point-in-polygon jurisdiction lookup, shared by the domain packages.

Two tools need the same question answered: `registry.resolve_jurisdiction`
with a coordinate, and `geo.resolve_location` with an address it has just
geocoded. ../../../design/architecture.md decision 0001 keeps the domain packages from importing each
other, so the shared half lives here rather than one domain reaching into
the other — and the split is worth having on its own, because the querying
and the envelope assembly are genuinely different jobs.

Nothing here builds an envelope. It registers provenance and evidence on
the caller's builder, and returns what was found; each tool says what that
means in its own words.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.assemble import EnvelopeBuilder, failure, selection_coverage
from ..core.envelope import (AccessPath, RegistryCoverage, SourceFailure,
                             WarningCode)
from ..core.errors import CommonwealthError
from ..core.jurisdiction import Jurisdiction
from ..core.registry import SourceManifest
from ..runtime import RuntimeContext

# Point-in-polygon runs against the statewide boundary source, so the
# selection stack is the state itself — the whole point is that the
# jurisdiction is not yet known.
STATEWIDE_STACK = ["va"]

# How close to another jurisdiction's boundary a point may sit before the
# answer is flagged as boundary-sensitive. This is a COMMONWEALTH-CHOSEN
# screening tolerance, not a publisher-stated accuracy figure: VGIN states
# none for the administrative-boundary layer, and inventing one would be a
# guess dressed as a measurement. The buffered query runs against the
# layer's true geometry, so the number means what it says; what it cannot
# tell you is how far the published line sits from the legal line.
BOUNDARY_PROXIMITY_METERS = 50


@dataclass
class Containment:
    """What the boundary source said about one coordinate."""

    manifest: SourceManifest | None = None
    source_ref: str | None = None
    registry_dim: RegistryCoverage = RegistryCoverage.unknown
    gaps: list = field(default_factory=list)
    failures: list[SourceFailure] = field(default_factory=list)
    # Narrowest first: the town if there is one, then the containing
    # locality. Each entry is {source_name, source_fips, layer,
    # jurisdiction}.
    town: list[dict] = field(default_factory=list)
    locality: list[dict] = field(default_factory=list)
    nearby: list[str] = field(default_factory=list)
    # Layers that errored. A failure of the TOWNS layer is not the same
    # as a failure of the localities layer: towns are the narrower
    # government, so losing that query means the narrowest answer is
    # unknown rather than absent, and the county below it is a plausible
    # wrong answer rather than a partial one.
    failed_layers: list[str] = field(default_factory=list)
    # Evidence ids for the polygons that were actually hit, so a caller
    # can trace which boundary supports the government it was given.
    evidence_refs: list[str] = field(default_factory=list)

    @property
    def unreachable(self) -> bool:
        """The source was selected and every query against it failed."""
        return bool(self.failures) and self.source_ref is None

    @property
    def empty(self) -> bool:
        return not self.town and not self.locality

    @property
    def narrowest_unknown(self) -> bool:
        """True when the towns layer failed while localities answered.

        The county is then a plausible WRONG government rather than a
        partial answer: the point may sit in a town whose polygon was
        never retrieved, and a caller routing later queries through the
        county would get the wrong government's records with no sign
        anything was missed. Coverage says partial either way, which is
        not enough — the material answer has to be withheld."""
        return "towns" in self.failed_layers and bool(self.locality)

    @property
    def leaf(self) -> dict | None:
        """The narrowest government containing the point. A town is
        narrower than the locality that contains it; the locality is
        reported alongside, never replaced.

        None when the towns layer failed: see `narrowest_unknown`."""
        if self.narrowest_unknown:
            return None
        hits = self.town or self.locality
        return hits[0] if hits else None

    def layered(self, ctx: RuntimeContext) -> list[dict[str, str]]:
        """The stack above the leaf. A town's containing locality comes
        from the polygon that was actually hit, not from the table's
        parent link, so a disagreement between the two is visible rather
        than papered over."""
        rows: list[dict[str, str]] = []
        for entry in self.locality if self.town else []:
            j = entry["jurisdiction"]
            rows.append({
                "id": j.id if j else f"unmapped:{entry['source_fips']}",
                "relationship": "containing-locality",
                "name": entry["source_name"] or ""})
        leaf = self.leaf
        resolved = leaf["jurisdiction"] if leaf else None
        if resolved is not None:
            # A cross-county town's `parent` names ONE of its counties,
            # and a point in the other part is not in that one. The
            # containing locality was retrieved from the polygon that
            # actually holds this coordinate, so it wins: a static county
            # parent that contradicts it is dropped rather than listed as
            # an applicable authority. Everything above the county — the
            # state — still applies wherever the point is.
            containing_ids = {row["id"] for row in rows
                              if row["relationship"] == "containing-locality"}
            for p in ctx.jurisdictions.parents_of(resolved):
                if any(row.get("id") == p.id for row in rows):
                    continue
                if (containing_ids
                        and p.kind.value in ("county", "independent-city")
                        and p.id not in containing_ids):
                    continue
                rows.append({"id": p.id,
                             "relationship": "parent-" + p.kind.value,
                             "name": p.name})
        return rows


def _identify(ctx: RuntimeContext, layer: str, rec) -> dict:
    """Map one boundary polygon back to the project's own table."""
    canon = rec.canonical
    j: Jurisdiction | None
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


async def resolve_point(ctx: RuntimeContext, b: EnvelopeBuilder,
                        lon: float, lat: float,
                        reuse_source_ref: str | None = None) -> Containment:
    """Query the registered boundary source at a coordinate.

    Two layers are consulted because Virginia stacks governments: an
    incorporated town and its parent county both contain the same ground,
    and 'whose zoning' and 'whose schools' have different answers there.
    """
    out = Containment()
    # Placing several coordinates in one call consults one source several
    # times, and registering it once per placement puts the same source
    # in `provenance` repeatedly. The caller passes back the ref it got
    # from the first placement.
    out.source_ref = reuse_source_ref
    selected = ctx.sources.select("boundary.lookup", STATEWIDE_STACK)
    out.registry_dim, out.gaps = selection_coverage(
        ctx.sources, "boundary.lookup", STATEWIDE_STACK, selected, builder=b)
    if not selected:
        return out

    m = selected[0]
    out.manifest = m
    hits: dict[str, list] = {"localities": [], "towns": []}
    near: dict[str, list] = {"localities": [], "towns": []}
    for layer in ("localities", "towns"):
        try:
            q = await ctx.arcgis.query(m, layer, geometry_point=(lon, lat))
            buffered = await ctx.arcgis.query(
                m, layer, geometry_point=(lon, lat),
                distance_meters=BOUNDARY_PROXIMITY_METERS)
        except CommonwealthError as err:
            out.failures.append(failure(m.id, err.code, str(err)))
            out.failed_layers.append(layer)
            continue
        if out.source_ref is None:
            out.source_ref = b.add_source(
                source_id=m.id, publisher=m.publisher.agency,
                system=m.adapter.type, dataset=m.name,
                jurisdiction=m.jurisdiction,
                authority_level=m.publisher.authority_level,
                access_path=AccessPath.cache if q.from_cache
                else AccessPath.live,
                source_updated_at=q.source_updated_at,
                retrieved_at=q.retrieved_at,
                cache_age_seconds=q.cache_age_seconds,
                terms_gap=m.access.terms_gap)
        for r in q.records:
            out.evidence_refs.append(b.add_evidence(
                source_ref=out.source_ref, record_id=r.record_id,
                retrieved_at=q.retrieved_at,
                transformations=q.transformations,
                payload_hash=q.payload_hash()))
        hits[layer] = q.records
        near[layer] = buffered.records

    out.town = [_identify(ctx, "towns", r) for r in hits["towns"]]
    out.locality = [_identify(ctx, "localities", r) for r in hits["localities"]]

    # Straddle check: anything the buffered query reached that the exact
    # query did not is a different government within the tolerance.
    exact_ids = {r.record_id for layer in hits for r in hits[layer]}
    out.nearby = sorted({str(r.canonical.get("full_name"))
                         for layer in near for r in near[layer]
                         if r.record_id not in exact_ids})
    return out


def warn_if_near_a_border(b: EnvelopeBuilder, c: Containment) -> None:
    if not c.nearby:
        return
    b.warn(WarningCode.boundary_precision,
           f"This point is within {BOUNDARY_PROXIMITY_METERS} m of "
           f"{', '.join(c.nearby)}. The published boundary is "
           "cartographic and the publisher disclaims survey use, so "
           "which side of the line this point falls on is not settled "
           "by this answer. Confirm with the locality before relying "
           "on it.", c.manifest.id if c.manifest else None)
