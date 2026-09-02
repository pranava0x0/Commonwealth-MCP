#!/usr/bin/env python3
"""Everything this project knows about one address in Sterling.

Sterling is a Census Designated Place in Loudoun County: a postal city and
a statistical area with no government of its own. Loudoun has no parcel or
zoning layer registered here either, so it is an ordinary, populous place
that this project covers entirely through statewide sources.

That makes it the honest demonstration. One walk produces three different
kinds of answer — records found, records checked and absent, and no source
registered at all — and telling those apart is the thing this project is
built to do.
"""
from _common import heading, run, show_envelope

from commonwealth.domains.geo import (find_address, find_boundaries,
                                      find_buildings,
                                      find_environmental_sites,
                                      find_landmarks, find_parcel,
                                      find_roads, find_zoning,
                                      resolve_location)
from commonwealth.domains.registry import resolve_jurisdiction

ADDRESS = "21641 Ridgetop Cir, Sterling, VA 20166"


def _kind_of_answer(env) -> str:
    """The one sentence a caller has to read before anything else."""
    registry = env.coverage.registry.value
    result = env.coverage.result.value
    if registry == "none":
        return ("NOT COVERED — no source is registered, and the records "
                "may well exist")
    if env.coverage.execution.value == "failed":
        return "UNAVAILABLE — the source was asked and did not answer"
    if result == "empty":
        return "CHECKED, NOTHING FOUND — the source answered with no records"
    return "FOUND"


async def body(ctx) -> None:
    heading('"Sterling" is not a government')
    env = await resolve_jurisdiction(ctx, query="Sterling")
    print(f"  {env.data['note']}")

    heading("The address, though, resolves")
    env = await resolve_location(ctx, address=ADDRESS)
    geo = env.data["geocode"]
    lon, lat = geo["lon"], geo["lat"]
    print(f"  the envelope says:  {geo['postal_city'].title()}")
    print(f"  the government is:  {env.data['resolved']['name']} "
          f"(FIPS {env.data['resolved']['fips']})")
    print(f"  found at:           {lat:.5f}, {lon:.5f}")
    show_envelope(env)

    heading("Now ask everything about that point")
    walk = (
        ("the boundary of the government", find_boundaries,
         {"jurisdiction": "Loudoun County"}),
        ("the parcel", find_parcel, {}),
        ("the zoning", find_zoning, {}),
        ("the address record", find_address, {}),
        ("buildings on the ground", find_buildings, {}),
        ("roads serving it", find_roads, {}),
        ("public places nearby", find_landmarks, {}),
        ("monitored environmental sites", find_environmental_sites, {}),
    )
    for label, tool, extra in walk:
        args = {"jurisdiction": "Loudoun County", **extra}
        if "jurisdiction" in extra and tool is find_boundaries:
            pass
        else:
            args |= {"lon": lon, "lat": lat}
        env = await tool(ctx, **args)
        records = sum(block.get("record_count", 0)
                      for block in env.data.get("results") or [])
        print(f"  {label:33} {records:>3} record(s)  "
              f"{_kind_of_answer(env)}")
        if env.coverage.registry.value == "none":
            for hint in env.next_actions:
                print(f"  {'':33}      -> try {hint.suggested_capability}")

    heading("Why the three answers are not the same answer")
    print("  Zoning is NOT COVERED. Loudoun County has a zoning ordinance\n"
          "  and a zoning map; this project has no registered source for\n"
          "  them. Reporting that as unzoned land would be the worst\n"
          "  answer available.\n")
    print("  Public places came back CHECKED, NOTHING FOUND. The statewide\n"
          "  landmarks layer was queried and holds nothing within a\n"
          "  kilometre. That is a fact about the layer, not about\n"
          "  Sterling, which has schools and a library.\n")
    print("  Everything else was FOUND, from statewide layers, because\n"
          "  Loudoun publishes none of its own here yet.")


if __name__ == "__main__":
    raise SystemExit(run(__doc__.strip().splitlines()[0], body))
