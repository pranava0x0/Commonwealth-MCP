#!/usr/bin/env python3
"""Query government records for one address in Sterling, Loudoun County.

The example shows records found, no matches within a query radius, and a
subject with no registered source: the county's public meetings."""
from _common import heading, run, show_envelope

from commonwealth.domains.geo import (find_address, find_boundaries,
                                      find_buildings,
                                      find_environmental_sites,
                                      find_health_facilities,
                                      find_landmarks, find_parcel,
                                      find_roads, find_zoning,
                                      resolve_location)
from commonwealth.domains.civic import search_meetings
from commonwealth.domains.registry import resolve_jurisdiction

ADDRESS = "21641 Ridgetop Cir, Sterling, VA 20166"


_KIND_TEXT = {
    "NOT COVERED": "NOT COVERED — no source is registered, and the records "
                   "may well exist",
    "UNAVAILABLE": "UNAVAILABLE — the source was asked and did not answer",
    "CHECKED, NOTHING FOUND": "CHECKED, NOTHING FOUND — the source answered "
                              "with no records",
    "FOUND": "FOUND",
}


def _kind(env) -> str:
    """Which of the answers this is — read off coverage, never assumed."""
    if env.coverage.registry.value == "none":
        return "NOT COVERED"
    if env.coverage.execution.value == "failed":
        return "UNAVAILABLE"
    if env.coverage.result.value == "empty":
        return "CHECKED, NOTHING FOUND"
    return "FOUND"


def _kind_of_answer(env) -> str:
    """The one sentence a caller has to read before anything else."""
    return _KIND_TEXT[_kind(env)]


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
        ("hospitals and urgent care nearby", find_health_facilities, {}),
    )
    kinds: dict[str, list[str]] = {}

    def report(label: str, env) -> None:
        records = sum(block.get("record_count", 0)
                      for block in env.data.get("results") or [])
        print(f"  {label:33} {records:>3} record(s)  "
              f"{_kind_of_answer(env)}")
        if env.coverage.registry.value == "none":
            for hint in env.next_actions:
                print(f"  {'':33}      -> try {hint.suggested_capability}")
        kinds.setdefault(_kind(env), []).append(label)

    for label, tool, extra in walk:
        args = {"jurisdiction": "Loudoun County", **extra}
        if tool is not find_boundaries:
            args |= {"lon": lon, "lat": lat}
        report(label, await tool(ctx, **args))

    # Not everything a county does is a point on a map.
    report("the county's public meetings",
           await search_meetings(ctx, jurisdiction="Loudoun County",
                                 start_date="2026-09-01",
                                 end_date="2026-09-30"))

    # Read off what came back rather than written in advance. This
    # section used to say zoning was NOT COVERED as a literal, and went on
    # saying it after Loudoun County's zoning was registered.
    heading("Why these are not the same answer")
    if kinds.get("NOT COVERED"):
        print(f"  NOT COVERED: {', '.join(kinds['NOT COVERED'])}.\n"
              "  Loudoun County has these; this project has no registered\n"
              "  source for them. Reporting that as \"none\" would be the\n"
              "  worst answer available.\n")
    if kinds.get("CHECKED, NOTHING FOUND"):
        print(f"  CHECKED, NOTHING FOUND: "
              f"{', '.join(kinds['CHECKED, NOTHING FOUND'])}. The layer was "
              "queried and\n  returned no matching records. That is a fact "
              "about the layer, not about\n  Sterling.\n")
    if kinds.get("UNAVAILABLE"):
        print(f"  UNAVAILABLE: {', '.join(kinds['UNAVAILABLE'])}. The source "
              "was asked and did not answer —\n  an outage, not an absence.\n")
    if kinds.get("FOUND"):
        print(f"  FOUND: {', '.join(kinds['FOUND'])}.")
        print("  Each of these names its own source in the answer above.")

if __name__ == "__main__":
    raise SystemExit(run(__doc__.strip().splitlines()[0], body))
