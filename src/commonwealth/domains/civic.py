"""Civic tools: Code of Virginia section lookup (design/domain-servers.md
§ 4, first slice).

design/domain-servers.md sketches `civic.search_law` as full-text search;
what's actually built here is direct-citation lookup only (the site's own
search feature was not reverse-engineered) — named `get_code_section`
rather than `search_law` so the tool's name doesn't overclaim what it
does. Selection discipline matches geo (DECISIONS.md 0005 Chosen): the top two
selectable sources for the capability are queried and every per-source
result is surfaced, never merged into one answer.
"""
from __future__ import annotations

from ..adapters.virginia_law import CodeSection
from ..core.assemble import (EnvelopeBuilder, failure, result_dim,
                             selection_coverage)
from ..core.envelope import AccessPath, Coverage, Envelope, \
    ExecutionCoverage, PaginationCoverage
from ..core.errors import CommonwealthError
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
        ctx.sources, "code_section.lookup", _STATEWIDE_STACK, selected)

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
            "source_url": section.source_url, "evidence_ref": ev_ref}


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
