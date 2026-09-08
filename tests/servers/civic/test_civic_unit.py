"""Civic unit tier: get_code_section and browse_code, over replayed real
responses from the publisher."""
import pytest

from commonwealth.core.errors import InvalidQuery
from commonwealth.domains.civic import browse_code, get_code_section


async def test_found_section_returns_heading_and_text(cw_ctx):
    env = await get_code_section(cw_ctx, citation="1-500")
    assert env.coverage.result.value == "hit"
    assert env.coverage.registry.value == "covered"
    blk = env.data["results"][0]
    assert blk["found"] is True
    assert blk["citation"] == "1-500"
    assert "great seal" in blk["heading"].lower()
    assert any("Virtus" in p for p in blk["paragraphs"]), (
        "the recorded page's real body text must come through unmangled")
    assert blk["source_url"].endswith("/1-500/")
    assert blk["evidence_refs"] == [e.id for e in env.evidence][:1]


async def test_missing_section_is_a_clean_empty_not_an_error(cw_ctx):
    """The site 302-redirects an unknown section to its title's chapter
    listing rather than 404ing — a clean empty, not a fault."""
    env = await get_code_section(cw_ctx, citation="1-999999")
    assert env.coverage.result.value == "empty"
    assert env.coverage.execution.value == "complete"
    assert env.coverage.source_failures == []
    blk = env.data["results"][0]
    assert blk["found"] is False
    assert blk["source_ref"] is None, (
        "nothing to cite as provenance when nothing was found")


async def test_evidence_locator_is_the_live_page(cw_ctx):
    env = await get_code_section(cw_ctx, citation="1-500")
    ev = env.evidence[0]
    assert ev.locator == "https://law.lis.virginia.gov/vacode/1-500/"


async def test_heading_excludes_the_page_chrome_title(cw_ctx):
    """The page has an earlier, unrelated <h2 class='pg-title'>Code of
    Virginia</h2> in its header chrome, before the real section heading —
    a parser that doesn't scope to the section content picks up both and
    concatenates them into a wrong, doubled heading."""
    env = await get_code_section(cw_ctx, citation="1-500")
    blk = env.data["results"][0]
    assert blk["heading"] == "§ 1-500. The great seal."


# --- browse_code (GitHub issue #12) ----------------------------------------

async def test_no_arguments_lists_the_titles(cw_ctx):
    env = await browse_code(cw_ctx)
    blk = env.data["results"][0]
    assert blk["level"] == "title"
    assert env.coverage.result.value == "hit"
    numbers = [r["number"] for r in blk["records"]]
    assert "15.2" in numbers, numbers[:8]
    first = blk["records"][0]
    assert first["kind"] == "title"
    assert first["next"] == {"title": first["number"]}, (
        "a title row carries what to pass to reach its chapters")
    assert first["cite_with"] is None, "a title is not a citation"


async def test_a_title_lists_its_chapters(cw_ctx):
    env = await browse_code(cw_ctx, title="15.2")
    blk = env.data["results"][0]
    assert blk["level"] == "chapter"
    by_num = {r["number"]: r for r in blk["records"]}
    assert "22" in by_num, sorted(by_num)[:10]
    assert "ZONING" in by_num["22"]["name"].upper()
    assert by_num["22"]["next"] == {"title": "15.2", "chapter": "22"}


async def test_a_chapter_lists_sections_that_carry_their_citations(cw_ctx):
    """The point of the walk: it ends somewhere `get_code_section` can
    read. A section row that did not carry its citation would leave the
    caller to build one out of the numbering."""
    env = await browse_code(cw_ctx, title="15.2", chapter="22")
    blk = env.data["results"][0]
    assert blk["level"] == "section"
    numbers = [r["number"] for r in blk["records"]]
    assert "15.2-2200" in numbers, numbers[:6]
    row = next(r for r in blk["records"] if r["number"] == "15.2-2200")
    assert row["cite_with"] == {"citation": "15.2-2200"}
    assert row["next"] is None, "a section is the bottom of the walk"
    assert row["name"], "the publisher's own section title comes through"


async def test_a_title_the_code_does_not_have_is_a_clean_empty(cw_ctx):
    """The publisher answers an unknown title with an empty list and HTTP
    200, which is the same shape as a title with no chapters. The note
    says which question came back empty rather than guessing between
    them."""
    env = await browse_code(cw_ctx, title="99.9")
    assert env.coverage.result.value == "empty"
    assert env.coverage.execution.value == "complete"
    assert env.coverage.source_failures == []
    blk = env.data["results"][0]
    assert blk["record_count"] == 0
    assert "99.9" in blk["note"]
    assert "does not have" in blk["note"]


async def test_a_chapter_without_a_title_is_refused(cw_ctx):
    """A chapter number only identifies a chapter inside a title, so
    reading '22' alone would have to guess which title it meant."""
    with pytest.raises(InvalidQuery) as err:
        await browse_code(cw_ctx, chapter="22")
    assert "title" in str(err.value)


async def test_browsing_never_claims_to_be_a_search(cw_ctx):
    """The naming discipline that made the other tool `get_code_section`.
    There is no full-text search over the Code from any public endpoint
    (design/source-quirks.md § 18), and a tool that implied otherwise
    would be the overclaim this project keeps refusing to make."""
    from commonwealth.servers.build import registries

    spec = next(t for t in registries()["civic"].tools()
                if t.name == "civic.browse_code")
    assert "not a search" in spec.description
    assert "no full-text search" in spec.description
    env = await browse_code(cw_ctx, title="15.2")
    assert any("No full-text search" in lim
               for lim in env.coverage.known_limitations), (
        "the source's own limitation travels with the answer")
