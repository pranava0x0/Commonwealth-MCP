"""Staleness: a publisher's data measured against the publisher's own
declared cadence (GitHub issue #57).

`WarningCode.stale_source` was declared and emitted from nowhere. It is
the other half of `freshness_unavailable`: that one says the vintage is
unknown, this one says the vintage is known and older than the publisher
led you to expect.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from commonwealth.core.assemble import _age_seconds
from commonwealth.core.registry import CADENCE_GRACE, Freshness, SourceRegistry
from commonwealth.fixtures import replay_context
from commonwealth.runtime import SOURCES_DIR


def _freshness(cadence: str, source: str = "stated") -> Freshness:
    return Freshness(expected_cadence=cadence, cadence_source=source,
                     ttl_hint_seconds=3600)


# --- the threshold ---------------------------------------------------------

@pytest.mark.parametrize("cadence,days", [
    ("daily", 2), ("weekly", 14), ("monthly", 60),
    ("quarterly", 180), ("annually", 730),
])
def test_a_declared_cadence_sets_the_threshold(cadence, days):
    assert _freshness(cadence).stale_after_seconds() == days * 86_400
    assert days == (86_400 * {"daily": 1, "weekly": 7, "monthly": 30,
                              "quarterly": 90, "annually": 365}[cadence]
                    * CADENCE_GRACE) // 86_400


@pytest.mark.parametrize("cadence", ["unknown", "", "when we feel like it"])
def test_a_source_that_promises_nothing_is_not_judged(cadence):
    """No promise, no way to be behind one. Inventing a threshold would
    be this project deciding what 'current' means for someone else's
    data."""
    assert _freshness(cadence).stale_after_seconds() is None


@pytest.mark.parametrize("source", ["unknown", "Unknown", " unknown ", ""])
def test_a_cadence_nobody_can_source_is_not_a_promise(source):
    """`expected_cadence: daily` with `cadence_source: unknown` is a
    figure somebody wrote down without recording who said it. Holding
    the publisher to it would attribute a schedule to them that they may
    never have given (review of PR #56: two manifests declare `daily`
    that way)."""
    freshness = _freshness("daily", source)
    assert freshness.cadence_has_provenance() is False
    assert freshness.stale_after_seconds() is None


def test_a_written_out_provenance_counts():
    """Manifests write the provenance out rather than using the one-word
    vocabulary, and a quoted statement from the publisher is the
    strongest provenance there is."""
    stated = _freshness(
        "quarterly",
        'Stated by the publisher: "locator files are updated quarterly."')
    assert stated.cadence_has_provenance() is True
    assert stated.stale_after_seconds() == 180 * 86_400


def test_the_grace_factor_is_stated_once():
    """A daily feed read on Monday still showing Friday's edit is a
    weekend, not a fault — so the threshold is a multiple of the cadence
    and the multiple is written down rather than buried in a comparison.
    """
    assert CADENCE_GRACE == 2
    assert _freshness("daily").stale_after_seconds() == 2 * 86_400


# --- the age computation ---------------------------------------------------

def test_age_is_the_gap_between_vintage_and_retrieval():
    assert _age_seconds("2026-09-01T00:00:00Z",
                        "2026-09-11T00:00:00Z") == 10 * 86_400


def test_data_stamped_after_it_was_read_is_not_negatively_fresh():
    """A publisher stamping data ahead of when it was read reads as zero,
    not as freshness from the future."""
    assert _age_seconds("2026-09-11T00:00:00Z",
                        "2026-09-01T00:00:00Z") == 0


@pytest.mark.parametrize("updated,read", [
    ("not a date", "2026-09-01T00:00:00Z"),
    ("2026-09-01T00:00:00Z", "not a date"),
    (None, "2026-09-01T00:00:00Z"),
])
def test_an_unparseable_timestamp_makes_no_claim(updated, read):
    """A staleness claim computed from a string nobody could parse would
    be worse than no claim."""
    assert _age_seconds(updated, read) is None


# --- through the envelope --------------------------------------------------

def _entry(builder, manifest, updated, read):
    return builder.add_source(
        source_id=manifest.id, publisher=manifest.publisher.agency,
        system=manifest.adapter.type, dataset=manifest.name,
        jurisdiction=manifest.jurisdiction,
        authority_level=manifest.publisher.authority_level,
        access_path="live", source_updated_at=updated, retrieved_at=read,
        cache_age_seconds=0, manifest=manifest)


@pytest.fixture()
def builder():
    from commonwealth.core.assemble import EnvelopeBuilder

    return EnvelopeBuilder(server="t", server_version="0", tool="t",
                           contract_version="1", registry_revision="r",
                           adapters={})


@pytest.fixture(scope="module")
def stated_manifest():
    """A source whose manifest quotes the publisher on its cadence."""
    registry = SourceRegistry.load(SOURCES_DIR)
    m = registry.get("va-vdot-lrs-routes")
    assert m.freshness.expected_cadence == "annually", (
        "this test needs a source that declares a real cadence")
    assert m.freshness.cadence_has_provenance(), (
        "this test needs a source that says where its cadence came from")
    return m


@pytest.fixture(scope="module")
def unsourced_manifest():
    """A source whose manifest declares a cadence and does not say where
    the figure came from."""
    registry = SourceRegistry.load(SOURCES_DIR)
    m = registry.get("va-richmond-city-parcels-zoning")
    assert m.freshness.expected_cadence == "daily"
    assert not m.freshness.cadence_has_provenance(), (
        "this test needs a manifest with cadence_source: unknown; if "
        "Richmond's has since been recorded, point it at another")
    return m


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_source_past_its_own_cadence_says_so(builder, stated_manifest):
    now = datetime.now(timezone.utc)
    _entry(builder, stated_manifest, _stamp(now - timedelta(days=3 * 365)),
           _stamp(now))
    warnings = {w.code.value: w.message for w in builder._warnings}
    assert "stale_source" in warnings
    message = warnings["stale_source"]
    # The publisher's schedule, named as theirs.
    assert "annually" in message
    assert stated_manifest.publisher.agency in message
    assert "not a deadline this project set" in message


def test_a_source_within_its_cadence_stays_quiet(builder, stated_manifest):
    now = datetime.now(timezone.utc)
    _entry(builder, stated_manifest, _stamp(now - timedelta(days=30)),
           _stamp(now))
    assert "stale_source" not in {w.code.value for w in builder._warnings}


def test_an_unsourced_cadence_is_not_held_against_the_publisher(
        builder, unsourced_manifest):
    """Richmond's manifest says `daily` and `cadence_source: unknown`. A
    vintage weeks past a daily cadence is not called stale, because
    nothing records that the daily figure is Richmond's. The warning
    that used to fire here told callers the city "describes this source
    as updating daily", which the manifest does not support (review of
    PR #56)."""
    now = datetime.now(timezone.utc)
    _entry(builder, unsourced_manifest, _stamp(now - timedelta(days=30)),
           _stamp(now))
    codes = {w.code.value for w in builder._warnings}
    assert "stale_source" not in codes
    # The vintage is known, so the other freshness warning is wrong too.
    assert "freshness_unavailable" not in codes


def test_the_two_freshness_warnings_are_never_both_right(builder,
                                                         stated_manifest):
    """`freshness_unavailable` means the vintage is unknown and
    `stale_source` means it is known and old. One answer cannot be
    both."""
    _entry(builder, stated_manifest, None, _stamp(datetime.now(timezone.utc)))
    codes = {w.code.value for w in builder._warnings}
    assert "freshness_unavailable" in codes
    assert "stale_source" not in codes


def test_the_warning_fires_once_per_source_not_once_per_layer(
        builder, stated_manifest):
    """A tool reading two layers of one service adds the source entry
    twice, and the same sentence twice reads as two problems."""
    now = datetime.now(timezone.utc)
    old, read = _stamp(now - timedelta(days=3 * 365)), _stamp(now)
    _entry(builder, stated_manifest, old, read)
    _entry(builder, stated_manifest, old, read)
    codes = [w.code.value for w in builder._warnings]
    assert codes.count("stale_source") == 1


def test_a_real_tool_call_carries_the_warning(monkeypatch):
    """Through a tool over the recorded fixtures, so what is tested is
    the wiring from manifest to warning rather than the builder alone.

    VDOT's routes layer quotes the publisher on an annual cadence and
    reports a vintage. The recording is weeks old rather than years, so
    the cadence is shortened to a second here to make that vintage count
    as stale: the rule under test is the wiring, not the calendar.
    """
    from commonwealth.core import registry
    from commonwealth.domains.geo import find_roads

    monkeypatch.setitem(registry.CADENCE_SECONDS, "annually", 1)
    env = asyncio.run(find_roads(replay_context(), jurisdiction="Vienna",
                                 street_name="Center St"))
    stale = [w for w in env.warnings if w.code.value == "stale_source"]
    assert [w.source_id for w in stale] == ["va-vdot-lrs-routes"], (
        "the recorded VDOT routes layer reports a vintage and states an "
        "annual cadence; with that cadence shortened, the answer should "
        "say the layer is behind it")
    assert "annually" in stale[0].message


def test_a_real_tool_call_does_not_judge_an_unsourced_cadence(monkeypatch):
    """The same wiring, on the source whose `daily` has no recorded
    provenance. Even with the cadence shortened to a second, Richmond's
    parcel layer is not called stale."""
    from commonwealth.core import registry
    from commonwealth.domains.geo import find_buildings

    monkeypatch.setitem(registry.CADENCE_SECONDS, "daily", 1)
    env = asyncio.run(find_buildings(replay_context(),
                                     jurisdiction="Richmond City",
                                     pin="C0010126019"))
    assert "va-richmond-city-parcels-zoning" in {
        s.source_id for s in env.provenance}
    assert "stale_source" not in {w.code.value for w in env.warnings}


# --- every add_source call site hands over its manifest --------------------

def test_no_domain_adds_a_source_without_its_manifest():
    """`terms_gap` was threaded through as its own parameter and five of
    the seven call sites never passed it; nothing was lost only because
    the sources that declare a gap happened to be reached by the two
    that did. The manifest carries every such disclosure now, and this
    is the floor under that."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "commonwealth"
    offenders = []
    for path in (root / "domains").glob("*.py"):
        text = path.read_text()
        for match in re.finditer(r"add_source\(", text):
            # The call runs to its closing paren; the registry tool's own
            # entry describes project data rather than a registered
            # source and has no manifest to hand over.
            tail = text[match.end():match.end() + 700]
            call = tail.split(")\n")[0]
            if "PROJECT_SOURCE" in call:
                continue
            if "manifest=" not in call:
                line = text[:match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line}")
    assert offenders == [], (
        f"these add_source calls pass no manifest, so a terms gap or a "
        f"staleness warning on that source would be silently dropped: "
        f"{offenders}")
