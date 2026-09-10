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


def _freshness(cadence: str) -> Freshness:
    return Freshness(expected_cadence=cadence, cadence_source="stated",
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
def daily_manifest():
    registry = SourceRegistry.load(SOURCES_DIR)
    m = registry.get("va-richmond-city-parcels-zoning")
    assert m.freshness.expected_cadence == "daily", (
        "this test needs a source that declares a real cadence")
    return m


def test_a_source_past_its_own_cadence_says_so(builder, daily_manifest):
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _entry(builder, daily_manifest, old, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    warnings = {w.code.value: w.message for w in builder._warnings}
    assert "stale_source" in warnings
    message = warnings["stale_source"]
    # The publisher's schedule, named as theirs.
    assert "daily" in message
    assert "not a deadline this project set" in message


def test_a_source_within_its_cadence_stays_quiet(builder, daily_manifest):
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _entry(builder, daily_manifest, recent, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert "stale_source" not in {w.code.value for w in builder._warnings}


def test_the_two_freshness_warnings_are_never_both_right(builder,
                                                         daily_manifest):
    """`freshness_unavailable` means the vintage is unknown and
    `stale_source` means it is known and old. One answer cannot be
    both."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _entry(builder, daily_manifest, None, now)
    codes = {w.code.value for w in builder._warnings}
    assert "freshness_unavailable" in codes
    assert "stale_source" not in codes


def test_the_warning_fires_once_per_source_not_once_per_layer(builder,
                                                              daily_manifest):
    """A tool reading two layers of one service adds the source entry
    twice, and the same sentence twice reads as two problems."""
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    read = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    _entry(builder, daily_manifest, old, read)
    _entry(builder, daily_manifest, old, read)
    codes = [w.code.value for w in builder._warnings]
    assert codes.count("stale_source") == 1


def test_a_real_tool_call_carries_the_warning():
    """Through a tool over the recorded fixtures, so what is tested is
    the wiring from manifest to warning rather than the builder alone."""
    from commonwealth.domains.geo import find_buildings

    env = asyncio.run(find_buildings(replay_context(),
                                     jurisdiction="Richmond City",
                                     pin="C0010126019"))
    assert "stale_source" in {w.code.value for w in env.warnings}, (
        "the recorded Richmond parcel layer declares a daily cadence and "
        "its vintage is well past it; the answer should say so")


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
