"""Civic tools: the Code of Virginia, and local public meetings
(design/domain-servers.md § 4).

Three tools over two very different publishers. The Code is one
statewide text, read by citation (`get_code_section`) or walked through
its own table of contents (`browse_code`). Meetings are per locality
(`search_meetings`), and are the first thing this server reads that a
government published and a *vendor* serves — see
`adapters/agenda_platform.py` for why the manifests name both.

design/domain-servers.md sketches `civic.search_law` as full-text
search. It is still not built and, as of the 2026-09-09 re-check, still
cannot be: the publisher serves no full-text search from any public
endpoint (GitHub issue #12, design/source-quirks.md § 18). The tools
here are named for what they do — `get_code_section`, not `search_law` —
so a name never overclaims. Selection discipline matches geo
(../../../design/architecture.md decision 0005 Chosen): the top two
selectable sources for the capability are queried and every per-source
result is surfaced, never merged into one answer.
"""
from __future__ import annotations

from ..adapters.agenda_platform import (MAX_RANGE_DAYS, Meeting,
                                        check_range)
from ..adapters.virginia_law import CodeSection
from ..core.assemble import (EnvelopeBuilder, failure, result_dim,
                             resolve_frame, selection_coverage)
from ..core.envelope import AccessPath, Coverage, Envelope, \
    ExecutionCoverage, PaginationCoverage, WarningCode
from ..core.errors import CommonwealthError, InvalidQuery
from ..core.registry import SourceManifest
from ..core.toolreg import ToolRegistry, ToolSpec
from ..runtime import RuntimeContext

CIVIC_TOOLS = ToolRegistry(package="civic")

# The Code of Virginia is a single statewide text — no per-request
# jurisdiction resolution the way a locality-scoped geo query needs one.
_STATEWIDE_STACK = ["va"]


def _builder(ctx: RuntimeContext, tool: str) -> EnvelopeBuilder:
    return EnvelopeBuilder(server=ctx.server_name,
                           server_version=ctx.server_version, tool=tool,
                           contract_version="1",
                           registry_revision=ctx.sources.revision,
                           adapters=ctx.adapters)


async def get_code_section(ctx: RuntimeContext, citation: str) -> Envelope:
    b = _builder(ctx, "civic.get_code_section")
    selected = ctx.sources.select("code_section.lookup", _STATEWIDE_STACK)
    registry_dim, gaps = selection_coverage(
        ctx.sources, "code_section.lookup", _STATEWIDE_STACK, selected,
        builder=b)

    blocks: list[dict] = []
    failures = []
    found_any = False
    for m in selected:
        try:
            section = await ctx.virginia_law.get_section(m, citation)
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        block = _section_block(b, m, section, citation)
        blocks.append(block)
        found_any = found_any or section is not None

    execution = (ExecutionCoverage.complete if not failures
                else ExecutionCoverage.failed if not blocks
                else ExecutionCoverage.partial)
    coverage = Coverage(
        registry=registry_dim, execution=execution,
        pagination=PaginationCoverage.complete,
        result=result_dim(1 if found_any else 0),
        jurisdictions_searched=_STATEWIDE_STACK if selected else [],
        jurisdictions_unavailable=gaps,
        source_failures=failures,
        known_limitations=sorted({lim for m in selected
                                  for lim in m.coverage.known_limitations}))
    return b.build({"results": blocks}, coverage)


def _section_block(b: EnvelopeBuilder, m: SourceManifest,
                   section: CodeSection | None, citation: str) -> dict:
    if section is None:
        return {"source_ref": None, "source_id": m.id, "found": False,
                "note": f"no section {citation!r} at {m.id}"}
    src_ref = b.add_source(
        source_id=m.id, publisher=m.publisher.agency, system=m.adapter.type,
        dataset=m.name, jurisdiction=m.jurisdiction,
        authority_level=m.publisher.authority_level,
        access_path=AccessPath.live,
        source_updated_at=None, retrieved_at=_now(),
        cache_age_seconds=0, manifest=m)
    ev_ref = b.add_evidence(source_ref=src_ref, record_id=section.citation,
                            retrieved_at=_now(), transformations=[],
                            locator=section.source_url)
    return {"source_ref": src_ref, "source_id": m.id, "found": True,
            "citation": section.citation, "heading": section.heading,
            "paragraphs": section.paragraphs,
            "source_url": section.source_url,
            "evidence_refs": [ev_ref]}


def _now() -> str:
    from ..core.envelope import utc_now_iso
    return utc_now_iso()


CIVIC_TOOLS.register(ToolSpec(
    name="civic.get_code_section",
    description=(
        "Get the text of a Code of Virginia section by its citation "
        "(e.g. '1-500', '18.2-57'). Direct lookup only — this is not a "
        "full-text search; the caller must already know or have found "
        "the section number. Results carry the section's own citation "
        "history exactly as published, with a link to the live page. "
        "A missing section (repealed, renumbered, or never existed) "
        "returns found=False, not an error."),
    toolset="default", contract_version="1", fn=get_code_section))


async def browse_code(ctx: RuntimeContext, title: str = "",
                      chapter: str = "") -> Envelope:
    b = _builder(ctx, "civic.browse_code")
    selected = ctx.sources.select("code_structure.browse", _STATEWIDE_STACK)
    registry_dim, gaps = selection_coverage(
        ctx.sources, "code_structure.browse", _STATEWIDE_STACK, selected,
        builder=b)
    if chapter and not title:
        raise InvalidQuery(
            "a chapter number only identifies a chapter within a title; "
            "pass `title` as well, or pass neither to list the titles")

    blocks: list[dict] = []
    failures = []
    total = 0
    for m in selected:
        try:
            entries, url = await ctx.virginia_law.browse(m, title, chapter)
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        blocks.append(_browse_block(b, m, entries, url, title, chapter))
        total += len(entries)

    execution = (ExecutionCoverage.complete if not failures
                 else ExecutionCoverage.failed if not blocks
                 else ExecutionCoverage.partial)
    coverage = Coverage(
        registry=registry_dim, execution=execution,
        pagination=PaginationCoverage.complete,
        result=result_dim(total),
        jurisdictions_searched=_STATEWIDE_STACK if selected else [],
        jurisdictions_unavailable=gaps,
        source_failures=failures,
        known_limitations=sorted({lim for m in selected
                                  for lim in m.coverage.known_limitations}))
    return b.build({"results": blocks}, coverage)


def _browse_block(b: EnvelopeBuilder, m: SourceManifest,
                  entries: list, url: str, title: str, chapter: str) -> dict:
    src_ref = b.add_source(
        source_id=m.id, publisher=m.publisher.agency, system=m.adapter.type,
        dataset="code-of-virginia-contents", jurisdiction=m.jurisdiction,
        authority_level=m.publisher.authority_level,
        access_path=AccessPath.live,
        source_updated_at=None, retrieved_at=_now(),
        cache_age_seconds=0, manifest=m)
    level = "section" if chapter else "chapter" if title else "title"
    rows = [{"kind": e.kind, "number": e.number, "name": e.name,
             # What to pass back to reach the next level down, so a model
             # walking the Code does not have to infer the argument shape
             # from the numbering.
             "next": ({"title": e.number} if e.kind == "title" else
                      {"title": title, "chapter": e.number}
                      if e.kind == "chapter" else None),
             "cite_with": ({"citation": e.number} if e.kind == "section"
                           else None)}
            for e in entries]
    block = {"source_ref": src_ref, "source_id": m.id, "level": level,
             "records": rows, "record_count": len(rows), "source_url": url}
    if not rows:
        # The publisher answers an unknown title with an empty list and
        # HTTP 200, the same shape as a title that exists and has no
        # chapters. Neither is an error and the caller is told which
        # question came back empty rather than being left to guess.
        block["note"] = (
            f"no {level}s under "
            + (f"title {title!r} chapter {chapter!r}" if chapter
               else f"title {title!r}" if title else "the Code")
            + ". The publisher returns an empty list for a title or "
              "chapter it does not have, so this is either an empty "
              "branch or a number that is not in the Code.")
    return block


CIVIC_TOOLS.register(ToolSpec(
    name="civic.browse_code",
    description=(
        "Walk the Code of Virginia's table of contents. No arguments "
        "lists the titles; `title` lists that title's chapters; `title` "
        "and `chapter` list that chapter's sections. Each row carries "
        "the arguments for the next step down, and a section row carries "
        "the citation to pass to civic.get_code_section for its text. "
        "This is the publisher's own contents listing, not a search: "
        "there is no full-text search over the Code of Virginia from any "
        "public endpoint, so a question about what the law SAYS has to "
        "become a walk to a section and then a read of it. Headings are "
        "headings — a chapter named for zoning is not a promise about "
        "what its sections contain."),
    toolset="discovery", contract_version="1", fn=browse_code))


# The Code is one statewide text; meetings are not. This is the civic
# domain's first locality-scoped tool, so it resolves a jurisdiction the
# way the geo tools do rather than assuming the statewide stack above.
async def search_meetings(ctx: RuntimeContext, jurisdiction: str,
                          start_date: str, end_date: str,
                          body: str = "") -> Envelope:
    b = _builder(ctx, "civic.search_meetings")
    # Before anything else, and deliberately not inside the per-source
    # loop below. The adapter checks the window too, but down there a
    # raised InvalidQuery is caught by the `except CommonwealthError`
    # that records a SOURCE failure — so an out-of-range window came
    # back as `execution: failed` against a healthy publisher, which
    # blames the government for the caller's argument. A bad window is
    # bad whatever the registry covers, so it is refused here, once.
    check_range(start_date, end_date)
    frame = resolve_frame(ctx.jurisdictions, b, jurisdiction)
    if frame.early is not None:
        return frame.early
    stack = frame.stack or []

    selected = ctx.sources.select("meeting.search", stack)
    registry_dim, gaps = selection_coverage(
        ctx.sources, "meeting.search", stack, selected, builder=b)

    blocks: list[dict] = []
    failures = []
    total = 0
    for m in selected:
        try:
            meetings, url = await ctx.agendas.search_meetings(
                m, start_date, end_date, body or None)
        except CommonwealthError as err:
            failures.append(failure(m.id, err.code, str(err)))
            continue
        blocks.append(_meetings_block(b, m, meetings, url,
                                      start_date, end_date, body))
        total += len(meetings)

    execution = (ExecutionCoverage.complete if not failures
                 else ExecutionCoverage.failed if not blocks
                 else ExecutionCoverage.partial)
    coverage = Coverage(
        registry=registry_dim, execution=execution,
        # The publisher applies the date window itself and returns the
        # whole of it; there is no paging to be partway through.
        pagination=PaginationCoverage.complete,
        result=result_dim(total),
        jurisdictions_searched=stack if selected else [],
        jurisdictions_unavailable=gaps,
        source_failures=failures,
        known_limitations=sorted({lim for m in selected
                                  for lim in m.coverage.known_limitations}))
    return b.build({"results": blocks}, coverage)


def _meetings_block(b: EnvelopeBuilder, m: SourceManifest,
                    meetings: list[Meeting], url: str, start_date: str,
                    end_date: str, body: str) -> dict:
    # The publisher stamps every meeting with when it was last edited,
    # and that is the only freshness signal this platform gives. The
    # newest one in the answer is the vintage of the answer: nothing in
    # this window has been touched since. An empty window has no
    # timestamp and reports none, which is honest — with no records
    # there is no vintage, and `add_source` warns
    # `freshness_unavailable` for exactly that case.
    newest = max((x.last_modified for x in meetings if x.last_modified),
                 default=None)
    src_ref = b.add_source(
        source_id=m.id, publisher=m.publisher.agency, system=m.adapter.type,
        dataset=m.name, jurisdiction=m.jurisdiction,
        authority_level=m.publisher.authority_level,
        access_path=AccessPath.live,
        source_updated_at=newest, retrieved_at=_now(),
        cache_age_seconds=0, manifest=m)

    records = []
    for meeting in meetings:
        ev_ref = b.add_evidence(
            source_ref=src_ref, record_id=meeting.event_id,
            retrieved_at=_now(), transformations=[],
            locator=meeting.portal_url or url)
        record = {
            "body": meeting.body,
            "date": meeting.meeting_date,
            "time": meeting.meeting_time,
            "time_zone": meeting.time_zone,
            # The publisher's own value, and only ever that. It says
            # whether the AGENDA is final, which is not whether the
            # meeting is happening — the field name says so, and the
            # tool description says so again.
            "agenda_status": meeting.agenda_status,
            "location": meeting.location,
            # Links, returned as data and never followed.
            "agenda_url": meeting.agenda_url,
            "minutes_url": meeting.minutes_url,
            "portal_url": meeting.portal_url,
            "comment": meeting.comment,
            # When the publisher last edited this notice. The comment is
            # where a cancellation lives, so "when was this last
            # revised" is the difference between a cancellation posted
            # this morning and one posted years ago.
            "last_modified": meeting.last_modified,
            "evidence_refs": [ev_ref],
        }
        if meeting.cancellation_note:
            record["cancellation_note"] = meeting.cancellation_note
        records.append(record)

    cancelled = [r for r in records if "cancellation_note" in r]
    if cancelled:
        # Read from prose, so it is disclosed as a screening reading
        # rather than passed off as the publisher's own status.
        b.warn(WarningCode.screening_only,
               f"{len(cancelled)} of these meetings carry a comment saying "
               "the meeting was cancelled or rescheduled. This platform "
               "publishes no cancellation field, so that reading comes "
               "from the comment text, which is returned verbatim on each "
               "record. Read the comment before relying on it, and check "
               "the publisher's own page for anything that matters.",
               source_id=m.id)

    block = {"source_ref": src_ref, "source_id": m.id,
             "records": records, "record_count": len(records),
             "window": {"start_date": start_date, "end_date": end_date},
             "body_filter": body or None,
             "source_url": url}
    if not records:
        block["note"] = (
            f"{m.name} published no meetings between {start_date} and "
            f"{end_date}"
            + (f" for a body matching {body!r}" if body else "")
            + ". The source is registered and answered; this is an empty "
              "window, not an absence of coverage. Bodies this locality "
              "does not publish through the platform would not appear "
              "here either.")
    return block


CIVIC_TOOLS.register(ToolSpec(
    name="civic.search_meetings",
    description=(
        "Find a Virginia locality's public meetings between two dates — "
        "the body, when it meets, where, and a link to the agenda "
        "document. Both dates are required and the window is capped at "
        f"{MAX_RANGE_DAYS} days: there is no default range, because a "
        "silently widened query answers a different question. "
        "`body` narrows to bodies whose name contains it. "
        "Meetings come from the civic-tech platform the locality "
        "publishes through, not from the locality's own servers, and "
        "only a few Virginia localities are registered — a locality with "
        "no registered source returns coverage registry=none, which "
        "means this project has nowhere to look, never that the "
        "government does not meet. `agenda_status` is the publisher's "
        "status for the AGENDA, not for the meeting; the platform "
        "publishes no cancellation field at all, so a cancelled meeting "
        "is returned like any other with its comment text carrying the "
        "cancellation and a `cancellation_note` saying that reading came "
        "from prose. The agenda link is data and is never fetched, so "
        "what a meeting is ABOUT is not in this answer."),
    toolset="default", contract_version="1", fn=search_meetings))
