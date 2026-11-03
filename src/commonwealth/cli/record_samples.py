"""Repeat the dated examples without retaining whole legislative or election exports."""
import asyncio
import csv
import io
import json

from ..adapters.base import HttpFetcher, egress_policy_for
from ..adapters.public_records import PublicRecordsAdapter, csv_rows
from ..core.envelope import utc_now_iso
from ..core.errors import CommonwealthError, SourceSchemaChanged

SESSION, BILL, ACTION = "20251", "HB1600", "H02V2512236"
DATE, OFFICE, COUNTY = "2021-11-02", "Governor", "Accomack County"
ORDER = "A204_Z0081911"


async def known_lookup(adapter, m):
    if m.adapter.dataset == "lis":
        rows, _ = await adapter.lis(m, SESSION, BILL)
        votes, _ = await adapter.lis(m, SESSION, BILL, ACTION)
        return (len(rows) == 1 and rows[0]["bill"] == BILL and rows[0]["session"] == SESSION
                and len(votes) == 22 and all(v["action"]["History_refid"] == ACTION for v in votes))
    if m.adapter.dataset == "eva":
        rows, _ = await adapter.purchases(m, "", "", ORDER, 0)
        return len(rows) == 6 and all(r["Order_#"] == ORDER for r in rows)
    rows, _ = await adapter.elections(m, DATE, OFFICE, COUNTY)
    return any(r["candidate_name"] == "Total Votes Cast" and r["votes"] == "12897" for r in rows)


class SampleFetcher:
    def __init__(self, m):
        self.http = HttpFetcher(egress_policy_for(m, m.adapter.service_url))
        self.downloads = {}
        self.exchanges = []

    async def fetch_bytes(self, url):
        if url in self.downloads:
            return self.downloads[url].encode()
        rows = csv_rows(await self.http.fetch_bytes(url))
        file = url.rsplit("/", 1)[-1]
        if file == "VOTE.CSV":
            kept = [r for r in rows if r and r[0].strip() in {ACTION, "2518627"}]
        else:
            header = next(rows)
            kept = [header]
            for row in rows:
                record = dict(zip(header, row))
                if (file == "Members.csv" or record.get("Bill_id", "").strip() == BILL
                        or record.get("division_name") == COUNTY and record.get("division_type") == "Locality"
                        and record.get("election_date", "")[:10] == DATE and record.get("office_name") == OFFICE):
                    kept.append(row)
        buf = io.StringIO(newline="")
        csv.writer(buf).writerows(kept)
        self.downloads[url] = buf.getvalue()
        return self.downloads[url].encode()

    async def fetch_json(self, url, params):
        data = await self.http.fetch_json(url, params)
        self.exchanges.append({"url": url, "params": params, "response": data})
        return data


def sample_public(m, root):
    fetcher = SampleFetcher(m)
    if not asyncio.run(known_lookup(PublicRecordsAdapter(fetcher), m)):
        raise SourceSchemaChanged("The declared example now returns no rows; review before recording.")
    out = root / m.id / "public-records.json"
    out.parent.mkdir(exist_ok=True, parents=True)
    out.write_text(json.dumps({"source_id": m.id, "recorded_at": utc_now_iso(),
        "publisher": m.publisher.agency, "terms_url": m.access.terms_url,
        "selection": "CSV headers and selected rows for one published example, re-encoded as UTF-8. "
                     "CKAN records are requested with a field allowlist.",
        "downloads": fetcher.downloads, "exchanges": fetcher.exchanges}, indent=1) + "\n")
    print(f"Recorded {m.id}: {out.name}")
    return 0


def public_health(ctx, m):
    try:
        ok = asyncio.run(known_lookup(ctx.public_records, m))
        return "publisher's known example " + ("found" if ok else "missing"), ok
    except CommonwealthError as err:
        return str(err), False


async def sample_map(m, adapter, recorder, ctx):
    from .__main__ import _recording_adapter_for
    summary = {}
    layers = list(m.adapter.layers)
    for layer in layers:
        summary[f"health:{layer}"] = await adapter.health(m, layer)
        for point in ([(-76.295, 36.85), (-74.5, 36.5)] if layer != "outfalls"
                      else [(-77.436, 37.5407), (-74.5, 36.5)]):
            q = await adapter.query(m, layer, geometry_point=point,
                                    distance_meters=1609.0 if layer == "outfalls" else None)
            summary[f"{layer}:{point}"] = len(q.records)
    if "zones" in layers:
        from ..domains.geo import _parcel_geometry
        for sid, pin in [("va-fairfax-parcels-zoning", "0102 14  0231"),
                         ("va-richmond-city-parcels-zoning", "E0000720034")]:
            pm = ctx.sources.get(sid)
            pa, pr = _recording_adapter_for(pm)
            parcels = await pa.query(pm, "parcels", where_equals={"pin": pin}, return_geometry=True)
            recorder.exchanges.extend(pr.exchanges)
            for parcel in parcels.records:
                for layer in layers:
                    await adapter.query(m, layer, intersect_geometry=_parcel_geometry(parcel))
    return summary
