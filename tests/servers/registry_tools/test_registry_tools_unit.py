"""Registry-tool logic called directly (no MCP layer)."""
from commonwealth.domains.registry import (describe_source,
                                           resolve_jurisdiction,
                                           search_sources, source_status)


async def test_resolve_hit_carries_evidence_for_the_row(cw_ctx):
    env = await resolve_jurisdiction(cw_ctx, "Fairfax County")
    assert env.data["resolved"]["id"] == "va:fairfax-county"
    assert [e.record_id for e in env.evidence] == ["va:fairfax-county"]
    assert env.provenance[0].source_id == "commonwealth-jurisdictions"
    assert env.warnings == [], "project data must not fire the freshness "\
                               "warning meant for government layers"


async def test_resolve_empty_is_empty(cw_ctx):
    env = await resolve_jurisdiction(cw_ctx, "Narnia")
    assert env.coverage.result.value == "empty"
    assert env.requires_user_choice is False


async def test_search_with_no_hits_is_empty_not_error(cw_ctx):
    env = await search_sources(cw_ctx, text="submarines")
    assert env.data["record_count"] == 0
    assert env.coverage.result.value == "empty"


async def test_search_filters_compose(cw_ctx):
    env = await search_sources(cw_ctx, jurisdiction="va:fairfax-county",
                               capability="parcel.lookup")
    assert [s["id"] for s in env.data["sources"]] == [
        "va-fairfax-parcels-zoning"]


async def test_status_row_count_matches_registry(cw_ctx):
    env = await source_status(cw_ctx)
    assert env.data["record_count"] == len(cw_ctx.sources.manifests)


async def test_describe_reflects_manifest_fields(cw_ctx):
    env = await describe_source(cw_ctx, "va-fairfax-parcels-zoning")
    manifest = cw_ctx.sources.get("va-fairfax-parcels-zoning")
    assert env.data["source"]["authority_notes"] == manifest.authority_notes


# --------------------------------------------------------------------------
# search_sources word matching (GitHub issue #18). The old test was a raw
# substring over name+id, which broke in both directions as the registry
# grew: "road" matched "crossroads", and a multi-word query matched nothing
# because no single field held the whole string.
# --------------------------------------------------------------------------
from commonwealth.domains.registry import _matches_terms, _search_terms


class _Pub:
    def __init__(self, agency):
        self.agency = agency


class _Fake:
    """Minimal stand-in with the fields _matches_terms reads."""
    def __init__(self, name, mid, juris="va", pub="Somebody", caps=()):
        self.name, self.id, self.jurisdiction = name, mid, juris
        self.publisher, self._caps = _Pub(pub), set(caps)

    def capability_ids(self):
        return self._caps


FAIRFAX = _Fake("Fairfax County Parcels and Zoning (Open Data)",
                "va-fairfax-parcels-zoning", "va:fairfax-county",
                "Fairfax County government", {"parcel.lookup", "zoning.lookup"})
ROADS = _Fake("VDOT Crossroads Network", "va-vdot-crossroads", "va",
              "Virginia Department of Transportation", {"network.lookup"})


def test_multi_word_query_matches_across_fields():
    """'Fairfax County parcels' spans the name and the capability list. A
    substring test over one concatenated field found nothing."""
    assert _matches_terms(_search_terms("Fairfax County parcels"), FAIRFAX)


def test_a_term_matches_a_word_not_a_substring():
    """'road' must not match 'Crossroads'."""
    assert not _matches_terms(_search_terms("road"), ROADS)
    assert _matches_terms(_search_terms("crossroads"), ROADS)


def test_every_term_must_match_so_extra_words_narrow():
    assert _matches_terms(_search_terms("fairfax zoning"), FAIRFAX)
    assert not _matches_terms(_search_terms("fairfax zoning richmond"), FAIRFAX)


def test_prefix_matching_handles_plurals():
    assert _matches_terms(_search_terms("parcel"), FAIRFAX)
    assert _matches_terms(_search_terms("parcels"), FAIRFAX)


def test_punctuation_and_case_are_ignored():
    assert _matches_terms(_search_terms("FAIRFAX, county."), FAIRFAX)


def test_empty_query_matches_nothing_by_itself():
    """An empty query yields no terms, and the caller skips filtering."""
    assert _search_terms("") == []
    assert _search_terms("   ,  ") == []
