#!/usr/bin/env python3
"""Ask what this project actually covers before assuming it covers you.

An empty answer means one of two different things: the records were
searched and nothing matched, or no source is registered for that place
at all. Most systems show the same blank screen for both.
"""
from _common import heading, run, show_envelope

from commonwealth.domains.geo import find_zoning
from commonwealth.domains.registry import (describe_source, search_sources,
                                           source_status)


async def body(ctx) -> None:
    heading("Sources that can answer a zoning question")
    env = await search_sources(ctx, capability="zoning.lookup")
    for row in env.data["sources"]:
        print(f"  {row['id']:38} {row['jurisdiction']:22} "
              f"{row['authority_level']}")
    show_envelope(env)

    heading("A jurisdiction with a zoning source")
    env = await find_zoning(ctx, jurisdiction="Richmond City",
                            pin="C0010126019")
    print(f"  coverage.registry = {env.coverage.registry.value}: a source "
          "is registered and was queried")

    heading("A jurisdiction with none")
    env = await find_zoning(ctx, jurisdiction="Craig County",
                            pin="ANY-PIN")
    print(f"  coverage.registry = {env.coverage.registry.value}: no source "
          "is registered there, so this empty result says nothing about "
          "whether the parcel is zoned")
    show_envelope(env)

    heading("What one source says about itself")
    env = await describe_source(ctx, source_id="va-deq-water-quality-stations")
    src = env.data["source"]
    print(f"  {src['name']}")
    print(f"  publisher: {src['publisher']} ({src['authority_level']})")
    print(f"  terms reviewed: {src['last_verified']}")
    for lim in src["known_limitations"][:3]:
        print(f"  limitation: {' '.join(lim.split())[:100]}")
    show_envelope(env)

    heading("Registry state")
    env = await source_status(ctx)
    counts: dict[str, int] = {}
    for row in env.data["sources"]:
        counts[row["declared_state"]] = counts.get(row["declared_state"], 0) + 1
    for state, n in sorted(counts.items()):
        print(f"  {state}: {n}")
    print(f"  {env.data['note']}")


if __name__ == "__main__":
    raise SystemExit(run(__doc__.strip().splitlines()[0], body))
