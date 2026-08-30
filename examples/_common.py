"""Shared plumbing for the example scripts.

Each example is a real question with a printed answer, runnable two ways:

    python examples/<name>.py --fixtures    # recorded responses, no network
    python examples/<name>.py --live        # the real government services

`--fixtures` is the default so a first run cannot fail on a network, a
firewall, or a government service being down at the wrong moment.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Callable, Coroutine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from commonwealth.core.envelope import Envelope  # noqa: E402
from commonwealth.core.errors import CommonwealthError  # noqa: E402
from commonwealth.fixtures import replay_context  # noqa: E402
from commonwealth.runtime import RuntimeContext, load_context  # noqa: E402

WIDTH = 74


def run(description: str,
        body: Callable[[RuntimeContext], Coroutine[Any, Any, None]]) -> int:
    ap = argparse.ArgumentParser(description=description)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fixtures", action="store_true", default=True,
                      help="replay recorded responses (default; no network)")
    mode.add_argument("--live", action="store_true",
                      help="query the real government services")
    args = ap.parse_args()
    live = args.live
    ctx = load_context() if live else replay_context()
    print(f"{description}\n"
          f"{'live services' if live else 'recorded responses (--live for the real thing)'}")
    print("=" * WIDTH)
    try:
        asyncio.run(body(ctx))
    except CommonwealthError as err:
        print(f"\n{err.code}: {err}")
        return 1
    except AssertionError as err:
        # The replay fetcher raises this for a request it has no recording
        # for, which is the expected failure when an example is edited to
        # ask something new.
        print(f"\nNo recorded response for that request:\n  {err}\n"
              "Re-run with --live, or record it with "
              "`commonwealth sources sample <source-id>`.")
        return 1
    return 0


def heading(text: str) -> None:
    print(f"\n{text}\n{'-' * len(text)}")


def show_coverage(env: Envelope) -> None:
    """The five dimensions, printed every time. An empty answer means
    something different depending on which of them says why, so they are
    printed even when the answer is a hit."""
    c = env.coverage
    print(f"  coverage: registry={c.registry.value} "
          f"execution={c.execution.value} pagination={c.pagination.value} "
          f"result={c.result.value}")
    for gap in c.jurisdictions_unavailable:
        print(f"    gap: {gap.jurisdiction} ({gap.reason})")
    for fail in c.source_failures:
        print(f"    failed: {fail.source_id} ({fail.error})")


def show_sources(env: Envelope) -> None:
    for src in env.provenance:
        age = f", cached {src.cache_age_seconds}s" if src.cache_age_seconds \
            else ""
        print(f"  {src.id}: {src.source_id} ({src.authority_level.value}, "
              f"{src.access_path.value}{age})")
        print(f"    published {src.source_updated_at or 'no date published'}"
              f", retrieved {src.retrieved_at}")


def show_warnings(env: Envelope) -> None:
    for w in env.warnings:
        body = w.message if len(w.message) <= 300 else w.message[:297] + "..."
        print(f"  [{w.code.value}] {body}")


def show_envelope(env: Envelope) -> None:
    show_coverage(env)
    if env.provenance:
        print("  sources:")
        show_sources(env)
    if env.warnings:
        print("  warnings:")
        show_warnings(env)
    if env.requires_user_choice:
        print("  * requires_user_choice: present these to the user; the "
              "tool did not pick")
