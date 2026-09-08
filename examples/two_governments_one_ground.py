#!/usr/bin/env python3
"""One point in the Town of Vienna, answered by two governments.

A town sits inside its county and both govern the ground. Vienna publishes
its own zoning layer and no parcel layer; Fairfax County publishes both.
Asked for the zoning at one point, this project queries both layers and
returns both answers with their sources named. Asked by parcel number, it
reads the town's districts over the county's parcel polygon and says so.
"""
from _common import heading, run, show_envelope

from commonwealth.domains.geo import find_zoning
from commonwealth.domains.registry import resolve_jurisdiction

POINT = (-77.2653, 38.9012)  # Maple Avenue, in Vienna
PIN = "0384 02  0143"         # Fairfax County's number for the parcel there


def _districts(block: dict) -> str:
    return ", ".join(r["district"] for r in block["records"]) or "(none)"


async def body(ctx) -> None:
    heading("Whose ground is this?")
    env = await resolve_jurisdiction(ctx, lon=POINT[0], lat=POINT[1])
    resolved = env.data["resolved"]
    print(f"  resolved: {resolved.get('name') or resolved['id']}")
    for authority in env.data["layered_authorities"]:
        print(f"    also governs it: {authority.get('name') or authority['id']}")

    heading("The zoning at that point, from every registered layer")
    env = await find_zoning(ctx, jurisdiction="Vienna", lon=POINT[0],
                            lat=POINT[1])
    for block in env.data["results"]:
        print(f"  {block['source_id']}: {_districts(block)}")
    comparison = env.data.get("comparison")
    print("\n  districts agree: "
          + (str(comparison["agreement"]) if comparison else
             "no comparison; only one source answered"))
    show_envelope(env)

    heading("The same ground by parcel number")
    env = await find_zoning(ctx, jurisdiction="Vienna", pin=PIN)
    for block in env.data["results"]:
        borrowed = block.get("parcel_source_id")
        over = (f"read over {borrowed}'s parcel polygon" if borrowed
                else "read over its own parcel layer")
        print(f"  {block['source_id']}: {_districts(block)}  ({over})")
    show_envelope(env)
    print("\n  The town publishes no parcel layer, so its districts were read\n"
          "  over the county's polygon. The evidence for each of its\n"
          "  districts names that polygon and the source it came from.")


if __name__ == "__main__":
    raise SystemExit(run(__doc__.strip().splitlines()[0], body))
