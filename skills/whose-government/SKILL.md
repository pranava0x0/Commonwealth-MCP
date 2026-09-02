---
name: whose-government
description: >
  Work out which Virginia government covers a place, from a name, a street
  address, a ZIP code, or a coordinate. Use when someone asks who governs
  an address, which county or city a place is in, or which locality a ZIP
  covers. Independent cities sit outside the county they are named after,
  a town and its county both govern the same ground, and the city on an
  envelope is often not the government. It reports every government that
  applies, and asks rather than choosing when the input is ambiguous.
license: Apache-2.0
compatibility: >
  Requires Commonwealth-MCP v0.x under a profile routing boundary.lookup.
metadata:
  commonwealth:
    required_capabilities:
      - boundary.lookup
    optional_capabilities:
      - geocode.address
      - address.lookup
---

# Whose government

This is the first step of nearly every other question about a place, and
the one that goes wrong silently. A parcel ID, a permit, a tax rate, and a
zoning district all belong to a specific government, and answering with
the wrong one produces a confident, well-sourced, wrong answer.

## 1. Establish the frame

Virginia's structure is the reason this needs a walk rather than a lookup.

- **95 counties and 38 independent cities.** An independent city is not
  inside any county. Fairfax City is not in Fairfax County, Richmond City
  is not in Richmond County, and the two Richmonds are at opposite ends of
  the state.
- **189 incorporated towns**, each inside a county. A town and its county
  both govern that ground, and they govern different things.
- **Three cities gave up their charters and became towns** — South Boston
  in 1995, Clifton Forge in 2001, Bedford in 2013. Someone asking about
  "Bedford City" is asking about a government that no longer exists, and
  the right answer names the town it became.

## 2. Minimum data walk

Take whichever input the caller gave and stop as soon as the government is
established. This walk has no second step for most inputs.

**A name.** Resolve it directly. Three outcomes, and they are different:

- *One match.* Report it with the stack above it.
- *Several matches.* Stop. The result carries candidates with a
  distinguisher for each ("independent city, not the county"). Show them
  and ask. Do not pick, and do not use surrounding context to guess: the
  caller who says "Fairfax" may well mean the one you would not have
  chosen.
- *A former name.* "Bedford City" resolves to the town with a note saying
  the charter was given up and when. Pass the note on; someone using the
  old name is often working from an old document, and that matters to
  whatever they do next.

**A street address.** Geocode it with `geocode.address`, then place the
resulting point. Two things to carry through:

- The postal city is not the government. Mail addressed to Alexandria is
  frequently in Fairfax County. Say both, and say which is which.
- The geocoder may return several candidates in *different* governments.
  When it does, that is an ambiguous address, not a ranked list. Show the
  candidates rather than taking the highest score.

**A ZIP code.** A ZIP is a mail delivery route and routinely crosses
locality lines. Report every locality it touches. A single answer for a
multi-locality ZIP is a guess wearing a fact's clothes.

**A coordinate.** Place it against `boundary.lookup` directly. This is the
only input with no interpretation step, and the most reliable one.

## 3. Escalation table

| Finding | Next | Why |
|---|---|---|
| The point is inside a town | Report the town and its county, both | Both govern that ground; "whose zoning" and "whose schools" have different answers there |
| The answer carries a boundary-precision warning | Repeat it, and say the published line is not a survey | The point is near another government's line, and the published boundary is cartographic |
| Candidates came back | Stop and ask | Guessing here is the failure this walk exists to prevent |
| The caller is about to file, pay, or apply somewhere | Say the locality is where to confirm | A government's own office is authoritative about itself; this is a screening answer |
| The name matches nothing | Say so plainly, and offer the nearest matches by spelling | Virginia has places with confusable names, and an empty answer with no suggestion is a dead end |

## 4. Output contract

1. **The government, named in full.** "Fairfax County", never "Fairfax".
   Where the place is in a town, name the town and the county and say both
   apply.
2. **How it was determined.** By name, by alias, by former name, by
   geocoded address, or by point. Each carries different confidence, and
   the caller cannot tell them apart unless told.
3. **What made it ambiguous, if anything.** The postal city, the ZIP
   spanning localities, the near boundary.
4. **The layered authorities.** The state is always above; a town has its
   county; an independent city has neither a county nor a town.

## 5. Stop conditions

Done when the government is named and the stack is reported.

Refuse, and say why:

- **Which government has jurisdiction over a legal matter.** Territory and
  legal jurisdiction are different questions, and courts, school
  divisions, and service districts do not follow locality lines.
- **Which side of a boundary line a specific property sits on.** The
  published boundary is cartographic and the publisher disclaims survey
  use. The locality settles this, from its own records.
- **Anything about a place outside Virginia.** Say so rather than
  answering from general knowledge.
