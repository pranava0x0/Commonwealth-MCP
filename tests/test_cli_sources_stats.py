"""`commonwealth sources stats` (GitHub issue #2): the registry's
proposed/active split reported as a number.

The split is the project's coverage-debt measurement. Asserting it is
non-zero is what stops it silently returning to zero, which is how it read
before any proposed manifest existed.
"""
from __future__ import annotations

from commonwealth.cli.__main__ import registry_stats
from tests.conftest import build_ctx


def test_stats_reports_a_non_zero_proposed_count():
    stats = registry_stats(build_ctx())
    proposed = stats["by_declared_state"]["proposed"]
    assert proposed > 0, (
        "zero proposed manifests reads as zero coverage debt against a "
        "seed list of majors that are entirely unbuilt — "
        "design/source-registry.md § 6.3")
    assert stats["total"] == sum(stats["by_declared_state"].values())
    print(f"registry: {stats['total']} manifests, {proposed} proposed")


def test_stats_are_derived_from_the_registry_not_a_hand_typed_list():
    ctx = build_ctx()
    stats = registry_stats(ctx)
    assert stats["total"] == len(ctx.sources.manifests)
    assert (stats["capabilities_in_vocabulary"]
            == len(ctx.sources.capability_vocab))
    assert stats["jurisdictions_in_table"] == len(ctx.jurisdictions)


def test_inventory_rows_never_count_toward_capability_coverage():
    """A proposed manifest declares no capability, so it cannot make an
    unanswered capability look answered."""
    ctx = build_ctx()
    stats = registry_stats(ctx)
    answered = stats["capabilities_with_an_active_source"]
    unanswered = stats["capabilities_with_no_active_source"]
    assert answered + len(unanswered) == stats["capabilities_in_vocabulary"]
