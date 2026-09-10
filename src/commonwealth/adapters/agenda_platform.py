"""Agenda-platform adapter: public meetings from a civic-tech vendor's
API, one client identifier per locality (GitHub issue #13).

This is the first source in the registry whose data a government
published and a *vendor* serves. Everything registered before it —
parcels, zoning, boundaries, the Code — comes off a machine the
government itself runs, so `authority_level: primary` meant the
publisher and the host were the same body. Here they are not: the
records are the locality's own, the API is Granicus's, and the manifests
say so rather than letting the vendor inherit the locality's authority.

One adapter, many jurisdictions. The vendor serves every client from one
host, `webapi.legistar.com`, distinguished only by a path segment — the
client identifier — so registering a new locality is a manifest, not
code. That claim is only worth making if it is tested, so fixtures are
recorded for two localities on this platform (design/adapters.md § 1)
and the identifier lives in `AgendaPlatformParams.client`, never here.

What the platform does not publish is the interesting half. Surveyed
2026-09-09 across every Virginia locality slug tried:

  * On this platform with the public API enabled: Richmond City,
    Alexandria City, Albemarle County, Hampton City, Petersburg City.
  * Not on it: Fairfax County and Charles City County — the two
    localities with registered sources of their own — along with every
    other slug tried. The API answers those with an explicit
    "LegistarConnectionString setting is not set up in InSite for
    client", which is a client that does not exist rather than an
    outage. They publish agendas through a CMS as PDFs, and are
    registered as `proposed` inventory so the gap is written down.

The vendor's own host wildcards: `<anything>.legistar.com` answers HTTP
200, including slugs that are not clients, so a portal responding is not
evidence a locality is on the API. Only the API answers that question.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..core.errors import InvalidQuery, SourceUnavailable
from ..core.registry import SourceManifest, register_adapter_params
from .base import (HttpFetcher, JsonListFetcher, egress_policy_for,
                   log_source_call)


class AgendaPlatformParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_url: str  # e.g. https://webapi.legistar.com/v1
    # The vendor's per-locality identifier. Manifest data, not adapter
    # data: it is the whole of what distinguishes one locality's
    # meetings from another's on this platform, and putting it here is
    # what makes registering the sixth locality a file rather than a
    # patch. Path segment, so it is pattern-checked before it is used.
    client: str
    # Where a human reads the same calendar. Returned as data on every
    # record so an answer can be checked against the publisher's own
    # page; never fetched (the egress allowlist is pinned to the API
    # host, and this is a different one).
    portal_url: str | None = None
    # The platform publishes local wall-clock time with no offset — a
    # meeting at "3:00 PM" and nothing to say 3 PM where. The zone is a
    # fact about the locality rather than about this adapter, so it is
    # declared per manifest. Every Virginia locality is in one zone
    # today; the field exists so that stays a statement a manifest
    # makes rather than an assumption this code buries.
    timezone: str = "America/New_York"


register_adapter_params("agenda_platform", AgendaPlatformParams)


# The vendor's client identifiers are lowercase alphanumeric path
# segments. Checked rather than trusted for the reason the Code's
# numbers are: this becomes a URL path, and `client="../../v1/other"`
# would read a different locality's calendar and report it under this
# manifest's name — a wrong answer wearing a correct one's clothes.
_CLIENT = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# An unbounded date range is refused rather than silently defaulted
# (issue #13): a query with no end quietly returning a decade of
# meetings is a different question than the one asked, and the caller
# never learns it was changed.
MAX_RANGE_DAYS = 400

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# What the platform calls a meeting whose agenda it has finalised. There
# is no "cancelled" among them — see `_cancellation_note`.
_AGENDA_STATUS_FIELD = "EventAgendaStatusName"


@dataclass
class Meeting:
    """One meeting, in the publisher's own terms.

    `status` is the agenda's publication status, which is the only status
    this platform publishes — it is not the meeting's status, and the
    field name says `agenda_status` downstream for that reason.
    """

    body: str
    meeting_date: str          # ISO date, publisher's own
    meeting_time: str          # publisher's own string, e.g. "3:00 PM"
    time_zone: str             # from the manifest, not the payload
    agenda_status: str
    location: str
    agenda_url: str | None
    minutes_url: str | None
    portal_url: str | None
    comment: str               # free text, verbatim
    cancellation_note: str | None
    event_id: str
    last_modified: str | None


def _segment(value: str, field: str) -> str:
    if not _CLIENT.fullmatch(value):
        raise InvalidQuery(
            f"{field} {value!r} is not a valid agenda-platform client "
            "identifier. They are lowercase alphanumeric, e.g. "
            "'richmondva'.")
    return value


def _iso(value: str, field: str) -> date:
    if not _ISO_DATE.fullmatch(value or ""):
        raise InvalidQuery(
            f"{field} must be an ISO date, YYYY-MM-DD — got {value!r}.")
    try:
        return date.fromisoformat(value)
    except ValueError as err:
        raise InvalidQuery(f"{field} {value!r} is not a real date.") from err


def check_range(start_date: str, end_date: str) -> tuple[date, date]:
    """The date window, refused rather than defaulted when it is not one.

    Both ends are required and the span is capped. The alternative —
    filling in a missing end — answers a question the caller did not ask
    and returns it as though they had, which is the failure mode issue
    #13 names for this tool.
    """
    start = _iso(start_date, "start_date")
    end = _iso(end_date, "end_date")
    if end < start:
        raise InvalidQuery(
            f"end_date {end_date} is before start_date {start_date}.")
    if end >= date.max:
        # The publisher's filter is a half-open interval, so the query
        # below asks for the day AFTER `end` — and `date.max + 1 day`
        # raises OverflowError, which is not a CommonwealthError and so
        # escapes the domain and server wrappers as an untyped internal
        # failure, past the audit path a typed error takes. A window
        # ending at the last representable date is refused here, where
        # the refusal is the documented one.
        raise InvalidQuery(
            f"end_date {end_date} is the last date this calendar can "
            "express, and the query needs the day after it. Ask for a "
            "window that ends earlier.")
    span = (end - start).days + 1
    if span > MAX_RANGE_DAYS:
        raise InvalidQuery(
            f"the date range {start_date}..{end_date} spans {span} days, "
            f"over the {MAX_RANGE_DAYS}-day limit for one meetings "
            "query. Ask for a narrower window; there is no default "
            "range, because a silently widened query returns an answer "
            "to a different question.")
    return start, end


# The platform publishes no cancellation flag. Every event carries
# `EventAgendaStatusName` of "Final" or "Final-revised" — verified
# 2026-09-09 over 2,510 events across the three largest registered
# clients, where 28 meetings said in prose that they were cancelled and
# none of them said it in a field.
#
# So a cancellation is read out of free text or not at all. That is
# reported as what it is: a note derived from the publisher's comment,
# carried beside the comment itself so the caller can read the original,
# and never promoted into `agenda_status`, which stays the publisher's
# own value. Dropping a cancelled meeting instead would be the worse
# failure — an omitted cancellation reads as a meeting that will happen.
_CANCELLED = re.compile(r"\bcancel(?:l?ed|l?ation)\b", re.IGNORECASE)
_RESCHEDULED = re.compile(r"\bre-?scheduled?\b", re.IGNORECASE)


def _cancellation_note(comment: str) -> str | None:
    if not comment:
        return None
    if _CANCELLED.search(comment):
        what = "cancelled"
    elif _RESCHEDULED.search(comment):
        what = "rescheduled"
    else:
        return None
    return (f"The publisher's comment on this meeting says it was "
            f"{what}. This platform publishes no cancellation field, so "
            f"that is read from the comment text quoted in `comment`, "
            f"not from a status the publisher set. Read the comment "
            f"before relying on it.")


def _rows(payload: Any) -> list[dict]:
    """The publisher's array, refusing anything else.

    `fetch_json_list` has already refused a non-array body; this refuses
    an array of something other than objects, which would otherwise
    reach the record loop as attribute errors escaping past the
    `CommonwealthError` boundary the tool catches.
    """
    out = []
    for row in payload:
        if not isinstance(row, dict):
            raise SourceUnavailable(
                "the agenda platform returned a list of "
                f"{type(row).__name__}, not meeting records. Treat this "
                "as the service having changed or failed, not as an "
                "empty calendar.")
        out.append(row)
    return out


def _text(row: dict, key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value).strip()


def _utc(value: str) -> str | None:
    """One of the publisher's UTC timestamps, in this project's shape.

    The platform sends `2026-09-08T14:17:05.757` — no offset, and the
    field name is the only thing saying it is UTC. Sub-second precision
    on a "when was this notice last edited" timestamp is noise, so it is
    dropped, and the `Z` is added because every other timestamp in an
    envelope carries one and a reader should not have to know which
    fields are secretly UTC.

    Anything that is not the documented shape returns None rather than a
    guess: a freshness claim invented from an unparseable string is
    worse than admitting the vintage is unknown.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.rstrip("Z"))
    except ValueError:
        return None
    return parsed.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


class AgendaPlatformAdapter:
    version = "0.1.0"

    def __init__(self, fetcher: JsonListFetcher | None = None) -> None:
        self._fetcher = fetcher

    def _fetcher_for(self, manifest: SourceManifest,
                     service_url: str) -> JsonListFetcher:
        if self._fetcher is not None:
            return self._fetcher
        return HttpFetcher(policy=egress_policy_for(manifest, service_url))

    async def search_meetings(self, manifest: SourceManifest,
                              start_date: str, end_date: str,
                              body: str | None = None
                              ) -> tuple[list[Meeting], str]:
        """Meetings in a date window, as the publisher orders them.

        Returns the meetings and the URL they came from. The window is
        applied by the publisher through its own filter rather than by
        fetching everything and trimming: the caller's question travels
        to the service that can answer it, and the answer is the
        publisher's own selection.
        """
        p = AgendaPlatformParams.model_validate(
            manifest.adapter.model_dump(exclude={"type"}))
        start, end = check_range(start_date, end_date)
        client = _segment(p.client, "client")
        base = p.service_url.rstrip("/")
        url = f"{base}/{client}/events"

        # The platform's filter is a half-open interval on a datetime
        # column, so the exclusive upper bound is the day after the
        # caller's inclusive `end_date`. Asking for `le end_date` would
        # drop every meeting on the last day, whose timestamps are
        # midnight-plus-nothing only by accident of how this publisher
        # stores them.
        upper = end + timedelta(days=1)
        params: dict[str, Any] = {
            "$filter": (f"EventDate ge datetime'{start.isoformat()}' and "
                        f"EventDate lt datetime'{upper.isoformat()}'"),
            # The publisher's own ordering. This project does not
            # re-rank a publisher's results anywhere, and a meeting
            # calendar out of date order would be actively unhelpful.
            "$orderby": "EventDate",
        }
        fetcher = self._fetcher_for(manifest, p.service_url)
        payload = await fetcher.fetch_json_list(url, params)
        meetings = [self._meeting(row, p) for row in _rows(payload)]

        # Body filtering is this project's, not the publisher's, and is
        # applied after the fetch: the platform's `$filter` matches
        # `EventBodyName` exactly, and a caller asking for "planning"
        # means the Planning Commission. A substring match here is a
        # narrowing of the publisher's own answer, never a re-ordering
        # of it.
        if body:
            needle = body.casefold()
            meetings = [m for m in meetings if needle in m.body.casefold()]
        log_source_call(manifest, "search_meetings",
                        {"start_date": start_date, "end_date": end_date,
                         "body": body or ""}, len(meetings))
        return meetings, url

    @staticmethod
    def _meeting(row: dict, p: AgendaPlatformParams) -> Meeting:
        comment = _text(row, "EventComment")
        raw_date = _text(row, "EventDate")
        return Meeting(
            body=_text(row, "EventBodyName"),
            # The publisher stores a datetime whose time half is always
            # midnight and whose real time is the separate `EventTime`
            # string, so only the date half is read here. Reporting
            # "T00:00:00" as the meeting's time would be a fabricated
            # precision.
            meeting_date=raw_date[:10],
            meeting_time=_text(row, "EventTime"),
            # Not in the payload — the platform publishes local wall
            # time with no offset. The zone is a fact about the
            # locality, so it comes from the manifest, and a reader is
            # told which zone rather than left to assume one.
            time_zone=p.timezone,
            agenda_status=_text(row, _AGENDA_STATUS_FIELD),
            location=_text(row, "EventLocation"),
            # Links are data. Nothing in this project fetches them: the
            # egress allowlist is pinned per manifest to the API host,
            # and these point at the vendor's document host, so
            # following one would drive through the allowlist.
            agenda_url=_text(row, "EventAgendaFile") or None,
            minutes_url=_text(row, "EventMinutesFile") or None,
            portal_url=_text(row, "EventInSiteURL") or p.portal_url,
            comment=comment,
            cancellation_note=_cancellation_note(comment),
            event_id=_text(row, "EventId"),
            # The only freshness signal this platform publishes.
            # Carried through to the envelope, where it becomes both the
            # record's own `last_modified` and the source entry's
            # `source_updated_at` — without it every meetings answer
            # warned `freshness_unavailable` over a timestamp the
            # publisher had sent.
            last_modified=_utc(_text(row, "EventLastModifiedUtc")),
        )

    async def health(self, manifest: SourceManifest,
                     known_body: str | None = None) -> dict:
        """Liveness: does this client's calendar answer at all?

        The window is a fixed recent span rather than "the next 30
        days", so a probe run against a client with no upcoming
        meetings is not read as an outage. What is being checked is
        that the service answers this client with its documented shape;
        a real empty calendar is a healthy answer.
        """
        today = date.today()
        meetings, _ = await self.search_meetings(
            manifest, (today - timedelta(days=180)).isoformat(),
            today.isoformat())
        out: dict[str, Any] = {"window_days": 180,
                               "meetings": len(meetings)}
        if known_body:
            out["body"] = {"name": known_body,
                           "found": any(known_body.casefold()
                                        in m.body.casefold()
                                        for m in meetings)}
        return out
