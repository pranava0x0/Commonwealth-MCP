---
name: federal-site-screen
description: >
  Screen one piece of ground against Virginia's records and the federal
  environmental layers together: resolve the address, establish the
  parcel, then run the same point through flood hazard, contaminated-site
  and wetland screening on a partner server. Use when someone asks what
  environmental constraints apply to a property, whether a site is in a
  flood zone, or what would show up in an early due-diligence pass. Needs
  a second MCP server for the federal half, and says which half is missing
  when it is not there.
license: Apache-2.0
compatibility: >
  Requires Commonwealth-MCP v0.x under a profile routing parcel.lookup and
  geocode.address. The federal half requires a second server providing
  FEMA flood, EPA cleanup-site and USACE wetland screening — nepa-mcp
  (github.com/pnnl/nepa-mcp) is the one this walk was written against.
  Without it, the Virginia half still runs and the answer says the federal
  half was not checked.
metadata:
  commonwealth:
    required_capabilities:
      - geocode.address
      - parcel.lookup
    optional_capabilities:
      - boundary.lookup
      - zoning.lookup
      - environmental_site.lookup
      - building.lookup
    example_prompt: >
      Screen 21641 Ridgetop Cir, Sterling, VA 20166 for environmental
      constraints — flood, wetlands, and any cleanup sites nearby.
---

# Federal site screen

[[site-context-screen]] answers what is on and around a piece of ground
from Virginia's own layers, and its only environmental layer is the
state's water-quality monitoring stations. The constraints that stop a
project are mostly federal: the flood map, the wetland inventory, the
cleanup-site registers. Those are published, and a partner MCP server
already exposes them.

This walk is the join. Its whole difficulty is that the two halves come
from different servers with different provenance rules, and an answer that
blends them into one paragraph destroys the reader's ability to check
either. So it keeps two sets of claims over one point on the ground, and
says which server produced each.

## 1. Establish the frame

- **One point, carried forward unchanged.** Everything downstream keys off
  a coordinate. Geocode once, resolve the government once, and pass the
  same coordinate to every subsequent step, including the partner's. Two
  halves screened at two slightly different points is the failure mode
  that produces a confident, internally inconsistent answer.
- **The parcel is the unit a person cares about; the point is the unit the
  screens accept.** Report both, and say when a parcel is large enough
  that a single-point screen says little about the rest of it.
- **A screen tells you where to look next.** Flood zone, wetland presence
  and cleanup-site proximity come from layers whose publishers name a
  different authority as the one that determines each. The reader is one
  step from treating the answer as a finding, and the answer has to keep
  saying who decides.
- **The partner is not this registry.** Its coverage, its dates and its
  limits are its own. Nothing this project's provenance envelope says
  applies to the partner's rows, and vice versa.

## 2. Minimum data walk

**Step 1 — resolve the address to a point and a government.** Geocode the
address, then place the coordinate. Ambiguous candidates in different
governments stop the walk, as in [[whose-government]]: screening the wrong
point is worse than not screening.

**Step 2 — establish the parcel.** Look the parcel up at the point. Where
a locality and the statewide layer both answer, keep both, unranked. Where
neither does, say so; the screen can still run on the coordinate, and the
answer says the parcel was not established.

**Step 3 — add the Virginia context worth having.** The zoning district
where a source is registered, and the state's monitored sites near the
point. Both are optional and both are cheap. A monitored site is a station,
not a finding: it says the state samples there.

**Step 4 — run the federal screens on the same point.** On the partner
server, in this order, because the answers get more expensive:
`analyze_fema_nfhl_flood_hazard_screening` for flood hazard, then
`get_usace_wetland_regions_in_roi` for wetlands, then
`get_epa_acres_properties_in_roi` for assessed and cleaned-up properties
in the radius. Name the radius used, every time.

**Step 5 — compose, if it helps.** Where the partner offers a map
composition (`compose_environmental_map`), one image over the same point
is worth several paragraphs. It is an illustration of what was screened,
not additional evidence.

**Step 6 — report as two halves.** Virginia's findings with this project's
sources and dates; the federal findings with the partner's. Never merge
the citations.

## 3. Escalation table

| Finding | Next | Why |
|---|---|---|
| The partner server is not connected | Run the Virginia half and say the federal half was not checked | An unscreened site reported as clear is the worst output this walk can produce |
| A partner call fails or times out | Report that layer as unavailable, name it, keep the rest | "No wetlands returned" and "the wetland service did not answer" are opposite facts |
| The flood screen returns a zone | Quote the zone and the map panel and its date | A zone without its panel and effective date cannot be checked or re-run |
| No wetland region intersects | Say the inventory shows none at this point | The inventory is a mapped product; absence from it is not absence on the ground, and a delineation is what settles it |
| A cleanup site is within the radius | Give the distance and the radius | Proximity is meaningless without the radius that produced it |
| The parcel is large or split | Say a point screen speaks for the point | A hundred-acre parcel screened at its centroid has been screened at one spot |
| The reader mentions a permit, a purchase, or a filing | Say this is a screen and name who determines it | FEMA, the Corps, the state agency and the locality each determine their own; none of them is this answer |

## 4. Output contract

1. **The point and the government**, with how the point was arrived at and
   what the address resolved to.
2. **The parcel**, with its source or sources, or a statement that no
   parcel record was established.
3. **Virginia's findings**, each with the registered source that produced
   it and the date it was fetched.
4. **The federal findings**, each attributed to the partner server and its
   publisher, kept visibly separate from the Virginia half.
5. **The radius** used for every proximity answer.
6. **Which layers were not checked**, and why — not connected, failed, or
   no source registered. This list is not optional; it is what makes the
   rest of the answer readable.
7. **The screening caveat**, once, plainly: none of this is a
   determination, and each layer names its own determining authority.

## 5. Stop conditions

Done when both halves have been attempted and reported, with the
unchecked layers named.

Refuse, and say why:

- **Whether the site can be developed, permitted, or built on.** That is a
  determination by a named authority, and every layer here disclaims it.
- **Whether a wetland is present.** The inventory is a screening product.
  A jurisdictional determination comes from the Corps, from a delineation
  on the ground.
- **A flood insurance rating, or what a policy would cost.** The zone is
  an input to that and not the answer.
- **Any statement about contamination on the site itself** from a
  proximity hit. A cleanup site nearby is a cleanup site nearby.
- **Screening a point outside Virginia.** The Virginia half has nothing to
  say, and half a screen presented as a screen is the failure this walk is
  built to avoid.
