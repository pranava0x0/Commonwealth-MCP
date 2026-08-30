#!/usr/bin/env python3
"""Screen one parcel: who governs it, how it is zoned, what is on it.

The walk a property question actually takes, in the order it takes it.
Every answer carries the caveat that belongs to it — a GIS zoning layer
is screening evidence, a missing building footprint is not vacant land,
and a monitoring station is not a finding.
"""
from _common import heading, run, show_envelope

from commonwealth.domains.geo import (find_buildings,
                                      find_environmental_sites, find_parcel,
                                      find_zoning)

JURISDICTION = "Richmond City"
PIN = "C0010126019"


async def body(ctx) -> None:
    heading(f"1. The parcel record for PIN {PIN}")
    env = await find_parcel(ctx, jurisdiction=JURISDICTION, pin=PIN)
    for block in env.data["results"]:
        for row in block["records"]:
            print(f"  {block['source_id']}: pin={row.get('pin')} "
                  f"class={row.get('property_class')}")
    if "comparison" in env.data:
        print(f"  two sources agree on the PIN: "
              f"{env.data['comparison']['agreement']}")
    show_envelope(env)

    heading("2. How it is zoned")
    env = await find_zoning(ctx, jurisdiction=JURISDICTION, pin=PIN)
    for block in env.data["results"]:
        districts = sorted({r.get("district") for r in block["records"]})
        print(f"  {block['source_id']}: {', '.join(d for d in districts if d)}"
              f" (from {block.get('parcel_polygons_intersected', 0)} parcel "
              "polygon(s))")
    show_envelope(env)

    heading("3. What is built on it")
    env = await find_buildings(ctx, jurisdiction=JURISDICTION, pin=PIN)
    for block in env.data["results"]:
        for row in block["records"]:
            area = row.get("footprint_area_sq_m_approx")
            print(f"  footprint ~{area} sq m ground area "
                  f"(publisher's value {row.get('footprint_area_web_mercator_sq_m'):.0f} "
                  "is in Web Mercator, where area is inflated ~1.6x here)")
            print(f"    class {row.get('building_class')} "
                  f"({row.get('building_class_label') or 'no label published'}), "
                  f"record updated {row.get('record_updated_at')}")
    show_envelope(env)

    heading("4. Monitored environmental sites within a mile")
    env = await find_environmental_sites(ctx, jurisdiction=JURISDICTION,
                                         lon=-77.4360, lat=37.5407)
    for block in env.data["results"]:
        print(f"  {block['record_count']} station(s) on record")
        for row in block["records"][:3]:
            print(f"    {row.get('station_id')} on "
                  f"{row.get('stream_name')}, last sampled "
                  f"{row.get('last_sample_date')}")
    show_envelope(env)


if __name__ == "__main__":
    raise SystemExit(run(__doc__.strip().splitlines()[0], body))
