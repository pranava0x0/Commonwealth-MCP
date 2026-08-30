#!/usr/bin/env python3
"""A mailing address is not a government.

"6800 Beulah St, Alexandria, VA 22310" is a Fairfax County address. Every
system that reads the mailing city as the jurisdiction gets an entirely
plausible wrong government's records, which is the trap Virginia's
independent cities set for anyone handling its data.
"""
from _common import heading, run, show_envelope

from commonwealth.domains.geo import resolve_location
from commonwealth.domains.registry import resolve_jurisdiction


async def body(ctx) -> None:
    heading('An address whose mailing city is not its government')
    env = await resolve_location(
        ctx, address="6800 Beulah St, Alexandria, VA 22310")
    geo = env.data["geocode"]
    print(f"  geocoded to {geo['lat']:.5f}, {geo['lon']:.5f} "
          f"(score {geo['score']}, matched by {geo['matched_by']})")
    print(f"  the mailing address says: {geo['postal_city'].title()}")
    print(f"  the government is:        {env.data['resolved']['name']} "
          f"(FIPS {env.data['resolved']['fips']})")
    show_envelope(env)

    heading('A name that matches two governments')
    env = await resolve_jurisdiction(ctx, query="Fairfax")
    for cand in env.data["candidates"]:
        print(f"  {cand['name']:20} {cand['distinguisher']}")
    show_envelope(env)

    heading('A ZIP that crosses government boundaries')
    env = await resolve_location(ctx, zip_code="24450")
    for row in env.data["localities_touched"]:
        print(f"  {row['fips']}  {row['name']}")
    print(f"  {env.data['note']}")
    show_envelope(env)


if __name__ == "__main__":
    raise SystemExit(run(__doc__.strip().splitlines()[0], body))
