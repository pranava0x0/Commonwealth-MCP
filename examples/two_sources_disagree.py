#!/usr/bin/env python3
"""Two official sources, one road, and no attempt to reconcile them.

VDOT keeps a linear-referencing route inventory as the operating agency.
VGIN aggregates centerlines from local government submissions. They
describe the same road differently on purpose, and this project queries
both and shows both rather than picking one.
"""
from _common import heading, run, show_envelope

from commonwealth.domains.geo import find_roads


async def body(ctx) -> None:
    heading("Center Street in the Town of Vienna")
    env = await find_roads(ctx, jurisdiction="Vienna",
                           street_name="Center St")
    for block in env.data["results"]:
        names = sorted({r.get("street_name") for r in block["records"]})
        print(f"  {block['source_id']}")
        print(f"    {block['record_count']} record(s): "
              f"{', '.join(n for n in names if n)}")
    comparison = env.data["comparison"]
    print(f"\n  names agree: {comparison['agreement']}")
    print(f"  {' '.join(comparison['note'].split())}")
    show_envelope(env)

    heading("The same street asked of the county instead")
    env = await find_roads(ctx, jurisdiction="Fairfax County",
                           street_name="Center St")
    for block in env.data["results"]:
        print(f"  {block['source_id']}: {block['record_count']} record(s)")
    comparison = env.data["comparison"]
    print(f"\n  names agree: {comparison['agreement']}  <- not False. One "
          "source returned nothing, which is a different fact from the two "
          "contradicting each other.")
    print(f"  {' '.join(comparison['note'].split())}")


if __name__ == "__main__":
    raise SystemExit(run(__doc__.strip().splitlines()[0], body))
