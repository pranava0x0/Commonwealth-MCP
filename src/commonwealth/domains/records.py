"""Additional Virginia public records, published as a separate MCP tool profile."""
from __future__ import annotations

from pydantic import StrictInt

from ..adapters.public_records import purchase_locator
from ..core.assemble import failure, result_dim, selection_coverage
from ..core.envelope import (AccessPath, Coverage, Envelope, ExecutionCoverage, PaginationCoverage,
                             WarningCode, utc_now_iso)
from ..core.errors import CommonwealthError, InvalidQuery
from ..core.toolreg import ToolRegistry, ToolSpec
from ..runtime import RuntimeContext
from .geo import (MAX_PARCEL_POLYGONS, _borrow_parcel_polygons, _builder, _epoch_ms_to_iso,
                  _parcel_geometry, _records_block, _resolve_frame, _source_entry)

RECORD_TOOLS = ToolRegistry(package="records")


def record_tool(name, description):
    def register(fn):
        RECORD_TOOLS.register(ToolSpec(name="records." + name, description=description,
                                       toolset="records", contract_version="1", fn=fn))
        return fn
    return register


def _coverage(registry, gaps, stack, failures, answered, count, truncated, selected):
    return Coverage(registry=registry, jurisdictions_unavailable=gaps,
                    jurisdictions_searched=stack if selected else [], source_failures=failures,
                    execution=(ExecutionCoverage.complete if not failures else ExecutionCoverage.partial
                               if answered else ExecutionCoverage.failed),
                    pagination=(PaginationCoverage.truncated if truncated else PaginationCoverage.complete
                                if answered else PaginationCoverage.unknown),
                    result=result_dim(count), known_limitations=sorted({v for m in selected
                                                                      for v in m.coverage.known_limitations}))


async def _published(ctx, tool, cap, read, offset, *, remote_page=False):
    if type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise InvalidQuery("offset must be a nonnegative integer no greater than 1000000.")
    b = _builder(ctx, "records." + tool)
    selected = ctx.sources.select(cap, ["va"])
    registry, gaps = selection_coverage(ctx.sources, cap, ["va"], selected, builder=b)
    blocks, failures = [], []
    count, truncated = 0, False
    for m in selected:
        try:
            records, urls = await read(m)
        except InvalidQuery:
            raise
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        now = utc_now_iso()
        ref = b.add_source(source_id=m.id, publisher=m.publisher.agency, system=m.adapter.type,
                           dataset=m.name, jurisdiction=m.jurisdiction,
                           authority_level=m.publisher.authority_level, access_path=AccessPath.live,
                           source_updated_at=None, retrieved_at=now, cache_age_seconds=0, manifest=m)
        page = records if remote_page else records[offset:]
        rows = []
        for rec in page[:25]:
            locator = urls[0]
            if "contest_id" in rec:
                identity = f"{rec['election_id']}:{rec['contest_id']}:{rec['division_name']}:{rec['candidate_id']}"
            elif "session" in rec:
                identity = f"{rec['session']}:{rec['bill']}"
                if "member_id" in rec:
                    identity += f":{rec['action']['History_refid']}:{rec['member_id']}"
            else:
                identity = str(rec["_id"])
                locator = purchase_locator(m.adapter.service_url, rec)
            ev = b.add_evidence(source_ref=ref, record_id=str(identity), locator=locator,
                                retrieved_at=now, transformations=["selected_publisher_fields"])
            rows.append({**rec, "evidence_refs": [ev]})
        more = len(page) > 25
        blocks.append({"source_id": m.id, "source_ref": ref, "records": rows, "source_urls": urls,
                       "offset": offset, "next_offset": offset + 25 if more else None})
        count += len(rows)
        truncated |= more
    return b.build({"results": blocks}, _coverage(registry, gaps, ["va"], failures, bool(blocks),
                                                 count, truncated, selected))


@record_tool("get_bill", "Read a Virginia legislative session's bill record, published text-version identifiers and history. Pass session 20251 and bill HB1600, for example. History references identify actions for get_bill_votes.")
async def get_bill(ctx: RuntimeContext, session: str, bill: str, history_offset: StrictInt = 0) -> Envelope:
    if type(history_offset) is not int or not 0 <= history_offset <= 10000:
        raise InvalidQuery("history_offset must be between 0 and 10000.")
    async def read(m):
        rows, urls = await ctx.public_records.lis(m, session, bill)
        for row in rows:
            actions = row["history"]
            row.update(history=actions[history_offset:history_offset + 25], history_count=len(actions),
                       next_history_offset=history_offset + 25 if len(actions) > history_offset + 25 else None)
        return rows, urls
    env = await _published(ctx, "get_bill", "bill.lookup", read, 0)
    if any(r["next_history_offset"] is not None for b in env.data["results"] for r in b["records"]):
        env.coverage.pagination = PaginationCoverage.truncated
    return env


@record_tool("get_bill_votes", "Read the recorded member votes for one Virginia legislative bill action. Pass its session, bill and History_refid from get_bill; use next_offset for additional members.")
async def get_bill_votes(ctx: RuntimeContext, session: str, bill: str, history_ref: str, offset: StrictInt = 0) -> Envelope:
    return await _published(ctx, "get_bill_votes", "bill_votes.lookup",
                            lambda m: ctx.public_records.lis(m, session, bill, history_ref), offset)


@record_tool("get_election_results", "Read historical Virginia candidate and summary rows by election date, office and exact reporting locality (e.g. Accomack County). Locality totals only. No precinct summing or live winner calls. Offices: Governor, Lieutenant Governor, Attorney General, President, U.S. Senate, U.S. House, State Senate, State Representative.")
async def get_election_results(ctx: RuntimeContext, election_date: str, office: str, locality: str,
                               offset: StrictInt = 0) -> Envelope:
    if not locality.strip() or locality.strip().casefold() == "virginia":
        raise InvalidQuery("Name a reporting locality; statewide totals are not supported.")
    return await _published(ctx, "get_election_results", "election_results.lookup",
                            lambda m: ctx.public_records.elections(m, election_date, office, locality), offset)


@record_tool("search_purchases", "Search FY2025 eVA purchase-order lines by exact agency, vendor, or order number. Returns ordered amounts and status; these are not payments or open solicitations. Use next_offset to page.")
async def search_purchases(ctx: RuntimeContext, agency: str = "", vendor: str = "", order: str = "",
                           offset: StrictInt = 0) -> Envelope:
    return await _published(ctx, "search_purchases", "purchase_order.search",
                            lambda m: ctx.public_records.purchases(m, agency, vendor, order, offset),
                            offset, remote_page=True)


async def _spatial(ctx, tool, cap, jurisdiction, lon, lat, pin, layers, radius=None):
    if (lon is None) != (lat is None) or bool(pin) == (lon is not None):
        raise InvalidQuery("Supply a parcel PIN or a longitude and latitude together.")
    if lon is not None and not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise InvalidQuery("Longitude or latitude is outside the geographic coordinate range.")
    b = _builder(ctx, "records." + tool)
    frame = _resolve_frame(ctx, b, jurisdiction)
    if frame.early is not None:
        return frame.early
    stack = frame.stack or []
    selected = ctx.sources.select(cap, stack)
    registry, gaps = selection_coverage(ctx.sources, cap, stack, selected, builder=b)
    geometries, blocks, failures = [], [], []
    truncated = False
    note = None
    if pin and selected:
        parcel = await _borrow_parcel_polygons(ctx, b, stack, pin, failures, {})
        if parcel.found is None:
            note = "No usable parcel geometry was returned. Flood layers were not queried."
        else:
            pq = parcel.found
            truncated = pq.exceeded_transfer_limit or len(pq.records) > MAX_PARCEL_POLYGONS
            for rec in pq.records[:MAX_PARCEL_POLYGONS]:
                if not (rec.geometry or {}).get("rings"):
                    failures.append(failure(parcel.source_id, "SourceSchemaChanged", "Parcel polygon has no rings."))
                    continue
                ref = b.add_evidence(source_ref=parcel.source_ref, record_id=rec.record_id,
                                     retrieved_at=pq.retrieved_at, transformations=pq.transformations,
                                     locator=rec.locator)
                geometries.append(({"intersect_geometry": _parcel_geometry(rec)}, ref))
    elif not pin:
        geometries.append(({"geometry_point": (lon, lat), "distance_meters": radius}, None))
    for m in selected:
        for kwargs, parcel_ref in geometries:
            for layer in layers:
                try:
                    q = await ctx.arcgis.query(m, layer, **kwargs)
                except CommonwealthError as err:
                    failures.append(failure(m.id, err.code, f"{layer}: {err}"))
                    continue
                block = _records_block(b, _source_entry(b, m, q), q, m, ctx,
                                       {"jurisdiction": jurisdiction, "lon": lon, "lat": lat, "pin": pin,
                                        **({"radius_meters": radius} if radius is not None else {})})
                block["layer"] = layer
                if parcel_ref:
                    block["parcel_evidence_ref"] = parcel_ref
                for row in block["records"]:
                    if parcel_ref:
                        row["evidence_refs"].append(parcel_ref)
                    if layer == "panels":
                        row["effective_date"] = _epoch_ms_to_iso(row.get("effective_date"))
                blocks.append(block)
                truncated |= q.exceeded_transfer_limit
    message = ("Mapped flood zones and effective map panels are separate layers. No mapped zone does "
               "not establish low risk. This is not an insurance determination." if pin or "zones" in layers
               else "Outfalls mark permitted discharge locations, not violations or measured pollution.")
    b.warn(WarningCode.screening_only, message)
    coverage = _coverage(registry, gaps, stack, failures, bool(blocks),
                         sum(x["record_count"] for x in blocks), truncated, selected)
    if note and not failures:
        coverage.execution = ExecutionCoverage.partial
        coverage.jurisdictions_searched = []
    return b.build({"results": blocks, "note": note or message}, coverage)


@record_tool("find_flood_zones", "Intersect effective FEMA flood zones and map panels in Virginia with a point or the polygons of a parcel PIN. Reports each intersecting zone and panel with its effective date. An empty map is not a flood-risk determination.")
async def find_flood_zones(ctx: RuntimeContext, jurisdiction: str, lon: float | None = None,
                           lat: float | None = None, pin: str = "") -> Envelope:
    return await _spatial(ctx, "find_flood_zones", "flood_zone.lookup", jurisdiction, lon, lat,
                          pin, ("zones", "panels"))


@record_tool("find_permit_outfalls", "Find Virginia DEQ permitted discharge outfalls within a radius of a point. Returns permit and facility identifiers, not inspection or violation records. Radius is in metres (1–10000).")
async def find_permit_outfalls(ctx: RuntimeContext, jurisdiction: str, lon: float, lat: float,
                               radius_meters: float = 1609.0) -> Envelope:
    if not 1 <= radius_meters <= 10000:
        raise InvalidQuery("radius_meters must be between 1 and 10000.")
    return await _spatial(ctx, "find_permit_outfalls", "permit_outfall.lookup", jurisdiction, lon,
                          lat, "", ("outfalls",), radius_meters)
