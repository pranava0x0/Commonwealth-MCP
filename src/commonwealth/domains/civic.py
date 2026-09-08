"""Civic tools: Code of Virginia section lookup (design/domain-servers.md
§ 4, first slice).

design/domain-servers.md sketches `civic.search_law` as full-text search;
what's actually built here is direct-citation lookup only (the site's own
search feature was not reverse-engineered) — named `get_code_section`
rather than `search_law` so the tool's name doesn't overclaim what it
does. Selection discipline matches geo (../../../design/architecture.md decision 0005 Chosen): the top two
selectable sources for the capability are queried and every per-source
result is surfaced, never merged into one answer.
"""
from __future__ import annotations

from ..adapters.virginia_law import CodeSection
from ..core.assemble import (EnvelopeBuilder, failure, result_dim,
                             selection_coverage)
from ..core.envelope import AccessPath, Coverage, Envelope, \
    ExecutionCoverage, PaginationCoverage
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
        source_updated_at=None, retrieved_at=_now(), cache_age_seconds=0)
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
        source_updated_at=None, retrieved_at=_now(), cache_age_seconds=0)
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
