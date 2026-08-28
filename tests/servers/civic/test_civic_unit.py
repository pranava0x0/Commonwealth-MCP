"""Civic unit tier: get_code_section against a replayed real page."""
from commonwealth.domains.civic import get_code_section


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
    assert blk["evidence_ref"] in {e.id for e in env.evidence}


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
