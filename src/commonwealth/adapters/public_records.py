"""Bounded queries against Virginia's documented CSV exports and CKAN DataStore."""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from typing import Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict

from ..core.errors import InvalidQuery, SourceSchemaChanged
from ..core.registry import register_adapter_params
from .base import HttpFetcher, egress_policy_for


class PublicRecordsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset: Literal["lis", "elections", "eva"]
    service_url: str


register_adapter_params("public_records", PublicRecordsParams)

OFFICES = {"president": 1, "governor": 3, "lieutenant governor": 4, "u.s. house": 5,
           "u.s. senate": 6, "state representative": 8, "state senate": 9, "attorney general": 12}
EVA_RESOURCE = "b8dc22a8-e96e-460f-9d5c-8dede67fddda"
ORDER_FIELDS = ("_id", "Order_#", "Order_Line_Number", "Entity_Description", "Vendor_Name",
                "Ordered_Date", "Item_Description", "Line_Total", "Order_Status", "Contract_Number")


def purchase_locator(url, row):
    # The archive may be reloaded. Bind the resource row to the order and line,
    # so a reassigned numeric ID cannot point at an unrelated purchase.
    filters = {k: row[k] for k in ("_id", "Order_#", "Order_Line_Number")}
    return url + "?" + urlencode({"resource_id": EVA_RESOURCE, "filters": json.dumps(filters),
                                  "fields": ",".join(ORDER_FIELDS), "limit": 1})


def csv_rows(raw: bytes):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    try:
        yield from csv.reader(io.StringIO(text, newline=""), strict=True)
    except csv.Error as exc:
        raise SourceSchemaChanged("The publisher returned malformed CSV.") from exc


def table(raw, required):
    rows = csv_rows(raw)
    header = next(rows, [])
    if len(header) != len(set(header)) or not set(required) <= set(header):
        raise SourceSchemaChanged("The publisher's CSV is missing expected columns.")
    for row in rows:
        if not row:
            continue
        if len(row) != len(header):
            raise SourceSchemaChanged("The publisher's CSV row does not match its header.")
        yield dict(zip(header, (v.strip() for v in row)))


def session_bill(session, bill):
    bill = bill.strip().upper()
    if not re.fullmatch(r"20[0-9]{2}[1-9]", session) or not re.fullmatch(r"(?:HB|SB|HJ|SJ|HR|SR)[1-9][0-9]{0,4}", bill):
        raise InvalidQuery("Use a five-digit LIS session (such as 20251) and bill number (HB1600).")
    return bill


def election_query(day, office):
    try:
        parsed = date.fromisoformat(day)
        if parsed.isoformat() != day:
            raise ValueError
        year = parsed.year
    except ValueError:
        raise InvalidQuery("Use an election date in YYYY-MM-DD format.") from None
    key = office.strip().lower()
    if key not in OFFICES:
        raise InvalidQuery("Supported offices: " + ", ".join(OFFICES))
    search = {"global": {"years": {"from": year, "to": year}},
              "contests": {"offices": [{"id": OFFICES[key]}], "divisions": [], "candidates": []},
              "ballotQuestions": {"text": "", "types": [], "number": "", "divisions": []},
              "specialElectionsOnly": False, "voterStats": False, "stages": []}
    return {"search": json.dumps(search, separators=(",", ":"))}


class PublicRecordsAdapter:
    def __init__(self, fetcher=None):
        self.fetcher = fetcher

    def client(self, m):
        return self.fetcher or HttpFetcher(egress_policy_for(m, m.adapter.service_url))

    async def lis(self, m, session, bill, vote_ref=None):
        bill = session_bill(session, bill)
        if vote_ref is not None and not re.fullmatch(r"[A-Za-z0-9]{1,24}", vote_ref):
            raise InvalidQuery("Pass the exact history reference for the bill action.")
        root = f"{m.adapter.service_url}/{session}/"
        client = self.client(m)
        history_url = root + "HISTORY.CSV"
        cols = ("Bill_id", "History_date", "History_description", "History_refid")
        actions = [r for r in table(await client.fetch_bytes(history_url), cols)
                   if r["Bill_id"] == bill]
        if vote_ref is None:
            url = root + "BILLS.CSV"
            cols = ("Bill_id", "Bill_description", "Patron_name", "Full_text_doc1")
            rows = [r for r in table(await client.fetch_bytes(url), cols) if r["Bill_id"] == bill]
            if not rows:
                return [], [url, history_url]
            if len(rows) != 1:
                raise SourceSchemaChanged("Several bill rows have the same session and bill number.")
            row = rows[0]
            versions = [{"document": row[f"Full_text_doc{i}"], "date": row.get(f"Full_text_date{i}")}
                        for i in range(1, 7) if row.get(f"Full_text_doc{i}")]
            return [{"session": session, "bill": bill, "description": row["Bill_description"],
                     "patron": row["Patron_name"], "text_versions": versions,
                     "chapter": row.get("Chapter_id"), "history": actions,
                     "latest_actions": {body: {"action": row.get(f"Last_{body}_action"),
                                               "date": row.get(f"Last_{body}_action_date")}
                                        for body in ("house", "senate", "conference", "governor")}}], [url, history_url]
        matched = [r for r in actions if r["History_refid"] == vote_ref]
        if not matched:
            return [], [history_url]
        url = root + "VOTE.CSV"
        ballots = []
        seen_rows = False
        for r in csv_rows(await client.fetch_bytes(url)):
            if not r:
                continue
            seen_rows = True
            if not re.fullmatch(r"[A-Za-z0-9]{1,24}", r[0].strip()) or len(r) % 2 != 1:
                raise SourceSchemaChanged("The publisher returned an unexpected roll-call layout.")
            if r[0].strip() == vote_ref:
                ballots.append(r)
        if not seen_rows:
            raise SourceSchemaChanged("The publisher returned an empty roll-call export.")
        if not ballots:
            return [], [history_url, url]
        if len(ballots) != 1 or len(ballots[0]) % 2 != 1:
            raise SourceSchemaChanged("The recorded roll call has an unexpected member/vote layout.")
        members_url = root + "Members.csv"
        members = {r["MBR_MBRNO"]: r["MBR_NAME"] for r in table(
            await client.fetch_bytes(members_url), ("MBR_MBRNO", "MBR_NAME"))}
        ids, votes = ballots[0][1::2], ballots[0][2::2]
        return [{"session": session, "bill": bill, "action": matched[0], "member_id": i.strip(),
                 "member_name": members.get(i.strip()), "vote": v.strip()} for i, v in zip(ids, votes)
                if i.strip()], [url, history_url, members_url]

    async def elections(self, m, day, office, locality):
        params = election_query(day, office)
        url = m.adapter.service_url + "?" + urlencode(params)
        raw = await self.client(m).fetch_bytes(url)
        cols = ("election_date", "office_name", "division_type", "division_name", "vote_channel",
                "contest_id", "election_id", "election_type", "district_name", "primary_party", "candidate_id",
                "candidate_name", "candidate_party_name", "votes")
        rows = [{k: r[k] for k in cols} for r in table(raw, cols)
                if r["election_date"][:10] == day and r["office_name"].casefold() == office.strip().casefold()
                and r["division_type"] == "Locality" and not r["vote_channel"]
                and r["division_name"].casefold() == locality.strip().casefold()]
        return rows, [url]

    async def purchases(self, m, agency, vendor, order, offset):
        filters = {k: v.strip() for k, v in (("Entity_Description", agency), ("Vendor_Name", vendor),
                                              ("Order_#", order)) if v.strip()}
        if not filters or any(len(v) > 200 for v in filters.values()):
            raise InvalidQuery("Supply an exact agency, vendor, or order number (up to 200 characters).")
        params = {"resource_id": EVA_RESOURCE, "filters": json.dumps(filters, sort_keys=True),
                  "fields": ",".join(ORDER_FIELDS), "sort": "_id asc", "limit": 26,
                  "offset": offset, "include_total": "false"}
        url = m.adapter.service_url
        body = await self.client(m).fetch_json(url, params)
        result = body.get("result")
        if body.get("success") is not True or not isinstance(result, dict) or not isinstance(result.get("records"), list):
            raise SourceSchemaChanged("The DataStore did not return a successful records page.")
        rows = result["records"]
        if any(not isinstance(r, dict) or not set(ORDER_FIELDS) <= r.keys() for r in rows):
            raise SourceSchemaChanged("An order line is missing published fields.")
        return [{k: r[k] for k in ORDER_FIELDS} for r in rows], [url + "?" + urlencode(params)]
