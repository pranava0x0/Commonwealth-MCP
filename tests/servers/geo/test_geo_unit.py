"""Geo unit tier: tool logic against replayed sources, incl. the two-source
(0005-C) agreement and conflict paths via the synthetic secondary mirror."""
import pytest

from commonwealth.domains.geo import find_parcel, find_zoning
from tests.conftest import (build_ctx, make_secondary_manifest,
                            secondary_exchanges)


async def test_find_parcel_by_pin(cw_ctx, sample_pin):
    """Fairfax County has two real parcel.lookup sources on file (its own
    county layer plus VGIN's statewide aggregation — ../../../design/architecture.md decision 0005-C: query
    both, never rank), and the fixture PIN is real in both."""
    env = await find_parcel(cw_ctx, jurisdiction="Fairfax County",
                            pin=sample_pin)
    blocks = env.data["results"]
    assert len(blocks) == 2
    assert all(blk["records"][0]["pin"] == sample_pin for blk in blocks)
    assert env.coverage.result.value == "hit"
    assert env.data["comparison"]["agreement"] is True


async def test_statewide_source_scopes_pin_by_jurisdiction(cw_ctx, sample_pin):
    """VGIN's statewide layer spans every locality in one FeatureServer, and
    a locality-assigned PIN is not guaranteed unique across localities — an
    unscoped query could return another jurisdiction's parcel as a false
    hit. `sample_pin` is Fairfax County's real PIN; asked for under Roanoke
    County (a jurisdiction with no local source, so VGIN alone answers), it
    must come back empty, not misattributed to Roanoke County."""
    env = await find_parcel(cw_ctx, jurisdiction="Roanoke County",
                            pin=sample_pin)
    assert env.coverage.result.value == "empty"
    assert env.coverage.registry.value == "covered"
    assert env.data["results"][0]["record_count"] == 0


async def test_find_parcel_empty_is_empty_not_error(cw_ctx, recording):
    """The recorded no-match PIN: a clean empty over a covered registry —
    result=empty, execution=complete, and absolutely not an error."""
    no_match_pin = recording["summary"]["no_match_pin"]
    env = await find_parcel(cw_ctx, jurisdiction="Fairfax County",
                            pin=no_match_pin)
    assert env.coverage.result.value == "empty"
    assert env.coverage.registry.value == "covered"
    assert env.coverage.execution.value == "complete"
    assert env.coverage.source_failures == []
    assert all(blk["record_count"] == 0 for blk in env.data["results"])


async def test_two_sources_agree(sample_pin):
    ctx = build_ctx(extra_manifests=[make_secondary_manifest()],
                    extra_exchanges=secondary_exchanges())
    env = await find_zoning(ctx, jurisdiction="Fairfax County",
                            pin=sample_pin)
    assert len(env.data["results"]) == 2, "0005-C: both sources queried"
    comparison = env.data["comparison"]
    assert comparison["agreement"] is True
    assert comparison["compared_field"] == "district"
    # 4, not 2: each source's parcel lookup (the geometry that determines
    # the zoning answer) is its own consulted source, registered alongside
    # the zoning query itself — not folded silently into it.
    assert len(env.provenance) == 4
    assert all(blk.get("parcel_evidence_refs")
               for blk in env.data["results"])


async def test_zoning_no_match_still_registers_parcel_provenance(cw_ctx, recording):
    """A PIN with no parcel match means zoning was never queried — but the
    parcels layer WAS consulted. The block must reference that, not report
    zero consulted sources for a call that actually happened."""
    no_match_pin = recording["summary"]["no_match_pin"]
    env = await find_zoning(cw_ctx, jurisdiction="Fairfax County",
                            pin=no_match_pin)
    assert env.data["results"][0]["source_ref"] is not None
    assert len(env.provenance) >= 1


async def test_two_sources_conflict_is_surfaced_never_reconciled(sample_pin):
    ctx = build_ctx(extra_manifests=[make_secondary_manifest()],
                    extra_exchanges=secondary_exchanges(mutate_district="C-8"))
    env = await find_zoning(ctx, jurisdiction="Fairfax County",
                            pin=sample_pin)
    comparison = env.data["comparison"]
    assert comparison["agreement"] is False
    assert "note" in comparison
    values = {tuple(p["values"]) for p in comparison["per_source"]}
    assert values == {("R-3",), ("C-8",)}, (
        "both answers shown, neither reconciled away")


async def test_point_query_path(cw_ctx, recording):
    """The recorded point exchange came from the sampled parcel's first
    ring vertex; assert the path works and returns the envelope shape.

    Read from the summary's `sample_point` rather than by taking the
    first point exchange in the file. The recording gained a second
    point — the Sterling walk — and "the first one" silently became a
    coordinate in another county, which the Fairfax layer answers with
    nothing.
    """
    point = recording["summary"].get("sample_point")
    if not point:
        pytest.fail("recording carries no sample_point; re-run "
                    "`commonwealth sources sample va-fairfax-parcels-zoning`")
    env = await find_parcel(cw_ctx, jurisdiction="Fairfax County",
                            lon=point[0], lat=point[1])
    assert env.coverage.execution.value == "complete"


async def test_pin_and_point_together_rejected(cw_ctx):
    from commonwealth.core.errors import InvalidQuery
    with pytest.raises(InvalidQuery, match="exactly one"):
        await find_parcel(cw_ctx, jurisdiction="Fairfax County",
                          pin="x", lon=-77.3, lat=38.8)


async def test_zoning_pin_with_partial_point_rejected(cw_ctx):
    """A PIN plus only `lon` (no `lat`) must not silently fall through to
    the PIN path and ignore the stray coordinate — find_parcel already
    rejects this shape; find_zoning must too."""
    from commonwealth.core.errors import InvalidQuery
    with pytest.raises(InvalidQuery, match="lon and lat"):
        await find_zoning(cw_ctx, jurisdiction="Fairfax County",
                          pin="x", lon=-77.3)


async def test_unknown_jurisdiction_is_empty_with_guidance(cw_ctx):
    env = await find_parcel(cw_ctx, jurisdiction="Atlantis", pin="x")
    assert env.coverage.result.value == "empty"
    assert "resolve_jurisdiction" in env.data["note"]
