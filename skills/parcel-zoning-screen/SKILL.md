---
name: parcel-zoning-screen
description: >
  Screen one Virginia parcel for its zoning district. Use when someone asks
  what a parcel is zoned, what a PIN or tax map number allows, whether a use
  is by-right, or what the zoning is at a Virginia address or point. It
  resolves the government first, then reads the parcel and zoning records,
  and it reports districts found, records absent, and sources unavailable as
  three different answers. It does not decide whether a use is permitted.
license: Apache-2.0
compatibility: >
  Requires the commonwealth-geo tools of Commonwealth-MCP v0.x, served under
  a profile that routes parcel.lookup and zoning.lookup.
metadata:
  commonwealth:
    required_capabilities:
      - parcel.lookup
      - zoning.lookup
    optional_capabilities:
      - geocode.address
      - boundary.lookup
---

# Parcel zoning screen

This walk screens a parcel; it does not determine anything. Virginia
zoning is adopted by ordinance and drawn on an official zoning map. What this walk reads is a GIS layer a
locality publishes for reference, so the answer is evidence about the
record and never a ruling about the ground.

## 1. Establish the frame

Resolve the government before reading anything about the parcel. A PIN is
only unique inside the locality that issued it, so the same string can name
two parcels in two localities.

Resolve from whichever of these the caller gave:

| The caller gave | What to do |
|---|---|
| A locality name | Resolve it. "Fairfax" is not a locality: Fairfax County and Fairfax City are separate governments that share a name. |
| A street address | Geocode it with `geocode.address`, then resolve the resulting point. The postal city on an address is not the government. A letter addressed to Alexandria, VA is often in Fairfax County. |
| A point | Resolve the point directly, against `boundary.lookup`. |
| A town name | Resolve it and read the whole stack. A town and its county both govern that ground, and both may have a zoning source. |

**Stop and ask when the resolution is ambiguous.** Candidates come back in
the envelope with `requires_user_choice`, and the right move is to show
them and wait. Picking one and carrying on produces a confident answer
about the wrong government, which is worse than a question.

A point near a locality line resolves to the polygon that contains it and
warns that a neighbour is close. Repeat that warning to the caller; a
parcel near a boundary is exactly where the answer is worth doubting.

## 2. Minimum data walk

Consult two capabilities in this order, and stop at step 2 unless a
finding sends you to the escalation table.

**Step 1 — `parcel.lookup`.** Confirm the parcel exists and get its record.

- *A hit* gives the parcel and its polygons. More than one polygon for one
  PIN is normal and matters: the parcel is split, and the zoning step will
  report a district per polygon.
- *Empty with `coverage.registry: covered`* means this publisher has no
  parcel with that PIN. Check the PIN's shape against the locality's own
  format before concluding it does not exist. Publishers embed spacing
  ("0102 14  0231"), and a re-spaced PIN misses.
- *Empty with `coverage.registry: none`* means no parcel source is
  registered for this locality. Say that, and stop; there is nothing to
  screen.

**Step 2 — `zoning.lookup`.** Read the district on the parcel's ground.

- *A hit* gives one or more districts. Where the parcel is split across
  polygons, the districts are the union across all of them and the result
  says how many polygons were intersected. Report every district and say
  the parcel is split. Two districts here are not two sources disagreeing.
- *Two sources answering* means two governments or two publishers both
  cover this ground, and both answers are returned unranked. Report both
  and say they differ. Do not pick one, and do not average them.
- *Empty with `coverage.registry: covered`* means the zoning layer has no
  polygon on this parcel. That is a real gap in the publisher's data, not
  an absence of zoning.
- *Empty with `coverage.registry: none`* means no zoning source is
  registered for this locality. **Say "not covered", never "unzoned".**
  Fairfax County and Richmond City are the only governments with registered
  zoning sources. Elsewhere, this project has not registered where to read
  zoning. Reporting that gap as unzoned land is the worst answer this skill
  can give.

## 3. Escalation table

Consult something further because a finding sent you, not to be thorough.
Each row is a finding, not a step.

| Finding | Next | Why |
|---|---|---|
| The parcel is split across polygons with different districts | Report each district with the polygon count | The parcel has two zonings, and which part is which needs the map |
| Two sources return different districts | Report both, with each source named | Decision 0005: no ranking, disagreement is the finding |
| Zoning came back `registry: none` | Name the locality's own planning or zoning office as where the answer lives | A registry gap has an address in the real world |
| The parcel record carries a `proffered` flag or an ordinance number | Report it verbatim and say proffers are conditions attached to a rezoning, not part of the district | A proffered district's rules are not the district's rules |
| A source failed mid-walk (`coverage.execution: partial`) | Report what was read and what was not, and name the source that failed | A short answer that looks complete is the failure this prevents |
| The caller asks whether they may build something | Stop. Answer § 5 | Not a question a GIS layer answers |
| The zoning layer publishes no update date | Say the vintage is unknown and retrieval time is not vintage | Common in Virginia; neither Fairfax nor Richmond publishes one |

## 4. Output contract

Report four parts every time, in this order.

1. **The government.** Which locality, and the full stack when the parcel
   is in a town. Say how it was resolved when it was resolved from an
   address or a point.
2. **The evidence matrix.** One row per claim: the claim, the source that
   published it, when it was retrieved, and the evidence reference from
   the envelope. A district with no source named is not a finding.
3. **Unresolved gaps.** Each as its own kind: no source registered, source
   registered but returned nothing, source failed. Three different facts,
   three different sentences.
4. **The screening caveat, every time.** The GIS layer is a screening
   representation. The adopted zoning ordinance and the official zoning map
   govern, and the locality's zoning administrator is who confirms a
   district. Carry this in your own words; it is not a footnote to pass
   through.

## 5. Stop conditions

Done when steps 1 and 2 have answered and the escalation table has no
matching finding left.

Refuse, and say why in one sentence:

- **Whether a use is permitted.** The district is a fact; what it allows
  is in the ordinance text, which this walk does not read.
- **Whether anything will be approved.** No.
- **Setbacks, height limits, density, lot coverage.** These live in the
  ordinance, and quoting them from a GIS attribute would be inventing them.
- **What a parcel is worth**, or what it could be worth rezoned.
- **Whether the parcel is buildable.** Zoning is one of many constraints,
  and the others are not in this walk.

Each refusal ends the same way: name the locality's zoning administrator
or planning office as who answers it. A refusal that leaves the caller
with nowhere to go is half an answer.
