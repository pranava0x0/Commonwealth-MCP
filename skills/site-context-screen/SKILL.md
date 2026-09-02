---
name: site-context-screen
description: >
  Screen what is on and around one piece of Virginia ground: buildings,
  the roads serving it, nearby public places, and any state water-quality
  monitoring station near it. Use when someone asks what is at a location,
  whether a site is built on, or wants a first look at a property. Each
  layer is a screening source rather than an inventory, so an empty answer
  means that layer holds no record.
license: Apache-2.0
compatibility: >
  Requires Commonwealth-MCP v0.x under a profile routing building.lookup
  and environmental_site.lookup; road and landmark answers need the
  `spatial` toolset.
metadata:
  commonwealth:
    required_capabilities:
      - building.lookup
    optional_capabilities:
      - road.lookup
      - landmark.lookup
      - environmental_site.lookup
      - parcel.lookup
---

# Site context screen

A first look at one location from the layers Virginia publishes statewide.
Every answer here is what one published layer holds, and the gap between
that and what is on the ground is the whole subject of this walk.

## 1. Establish the frame

Resolve the government first, and get to a point.

Most of these layers are queried by coordinate rather than by parcel, so
the walk needs a point. When the caller gives an address, geocode it. When
they give a parcel ID, look the parcel up first: the parcel polygon is
what defines "on this ground", and the building step uses it rather than a
radius when it is available.

A radius covers a circle of ground, which a property is not. When the
walk falls back to one, say so in the answer: a caller who asked about a
single lot and gets everything within 250 m has been answered a different
question.

## 2. Minimum data walk

Ask for what the question needs, in this order, and stop when it is
answered. Running all four every time is the anti-pattern this walk is
built to avoid.

**Step 1 — `parcel.lookup`, when there is a parcel ID.** Gives the polygon
the rest of the walk can use. Skip it when the caller gave a point and did
not ask about a parcel.

**Step 2 — `building.lookup`.** Whether the ground is built on, and how
much of it.

- *A hit* gives footprints. Height, storey, and class fields are often
  null, which means the publisher holds no value rather than zero.
- *Area is published in Web Mercator*, where area is inflated by roughly
  1.6x at Virginia's latitudes. Both the publisher's figure and a
  converted approximation come back, each labelled. Use the labelled one
  and say which.
- *Empty is not vacant land.* Coverage of this derived layer varies by
  locality, and a missing footprint is most often a coverage gap.
- *A dense query truncates*, returning the inline records and a handle to
  the whole retrieved set. Report the count, and use the handle rather
  than treating the short list as the answer.

**Step 3 — `road.lookup`, when access or frontage is the question.** Two
official sources answer and they are expected to disagree, because VDOT
models routes and VGIN aggregates local centerlines. Report both. A
difference between them is usually a difference in how the road is
modelled, not an error. Centerlines are not right-of-way boundaries, so
this never establishes frontage or access rights.

**Step 4 — `landmark.lookup` and `environmental_site.lookup`, when the
question is about surroundings.**

- Landmarks are named public places, and each record names the
  organisation that is its authority. A place missing from the layer may
  simply never have been added.
- Environmental sites are DEQ's water-quality monitoring network and
  nothing else. Air, waste, and land programmes are not in it. A station
  on record means that spot is or was sampled. **An empty result never
  means the ground is clean**, and historic stations are included, which
  is what the last-sample date is for.

## 3. Escalation table

| Finding | Next | Why |
|---|---|---|
| The building query truncated | Read the handle in the warning, or narrow the radius | The records were retrieved; a short list read as the whole answer undercounts |
| Footprint area is quoted | Say which projection, and give the converted figure | A Web Mercator area is about 1.6x the real one at Virginia's latitudes |
| The two road sources disagree on a name | Report both with their sources | Decision 0005: disagreement is the finding, and neither is ranked |
| An environmental station is within the radius | Report the station and its last sample date, and stop | A station is a sampling location; it is not a finding about contamination |
| No station is on record | Say the DEQ water-quality network has none near this point | Silence here reads as an all-clear, and it is not one |
| The caller asks about contamination, safety, or suitability | Stop. Answer § 5 | No layer in this walk answers that |

## 4. Output contract

1. **The location, and how it was arrived at** — parcel polygon, geocoded
   address, or a radius around a point, with the radius stated.
2. **What each layer returned**, one line per layer, naming the layer's
   publisher. A layer that was not consulted is reported as not
   consulted, distinct from one that returned nothing.
3. **The three kinds of nothing, kept apart.** No record in a covered
   layer; no source registered for that capability; a source that failed.
4. **The screening caveat, in your own words.** Each of these is one
   published layer. None is an inventory, and the absence of a record is
   evidence about the layer.

## 5. Stop conditions

Done when the question is answered by the steps it needed.

Refuse, and say who does answer it:

- **Whether a site is contaminated, safe, or suitable for a use.** This
  walk reads a monitoring network, not an assessment. An environmental
  professional performs a site assessment.
- **Whether a property has legal access or frontage.** Centerlines are not
  right-of-way. A surveyor and the locality's records settle it.
- **How many buildings, dwellings, or units are on a site**, as a count to
  rely on. The layer's coverage varies and its attributes are often null.
- **What anything is worth.**
