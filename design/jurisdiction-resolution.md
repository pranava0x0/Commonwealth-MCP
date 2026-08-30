# Spec: Jurisdiction Resolution

**Plugs into:** architecture.md § 9.3 (Jurisdiction Resolution), § 7.1 (`commonwealth-registry` tools), § 28 (Source Selection)
**Status:** Draft for review. The jurisdiction ID scheme freezes at Gate A.
Point-in-polygon resolution (§ 2 `point` row, § 2.1 `point_in_polygon`
basis, § 3 cases 2 and 7, and the point half of case 4) shipped 2026-08-28
against VGIN's administrative boundaries; § 6's centroid property test was
falsified by the real geometries and is amended in place. Address/ZIP
resolution (§ 2 `address` and `zip` rows, § 4) remains unbuilt — both need
a registered geocoder.

Fixture accounting for § 3's eight traps, added 2026-08-28 and corrected
the same day after review: 2, 3, and 6 are built as tests; 1, 4, and 5
wait on the geocoder; 7 ships as a warning rather than candidates
(annotated below; policy call in the GitHub issues); 8 waits on Bedford's
jurisdiction-table rows, which the 14-row seed does not carry.

Case 4 was briefly counted as "built by point rather than address."
That overstated it and is corrected here. Two Vienna paths are tested: a
point inside the town resolves to the town with its county layered
(`test_resolve_by_point.py::test_point_in_town_reports_town_and_its_county`),
and the literal name "Vienna" resolves by alias
(`test_jurisdiction.py::test_vienna_carries_parent_stack_and_id`).

Neither is the trap. Case 4 names a postal *address*, and nothing in the
suite parses or geocodes one. Counting it built would let the eventual
address path ship without the regression this case exists to force, so it
stays in the geocoder-blocked group with 1 and 5 until an address fixture
exists.

**Why this exists:** Every Commonwealth query starts by answering "whose government?" Virginia makes this genuinely hard: 95 counties and 38 independent cities that are *not* inside counties (Fairfax City is not in Fairfax County), towns inside counties, overlapping authorities (regional bodies, school divisions, service districts), and addresses whose postal city names a place that is not their jurisdiction (a "Alexandria, VA" mailing address can sit in Fairfax County). Getting this wrong silently returns the wrong government's records, which is worse than failing.

---

## 1. The jurisdiction model

```json
{
  "id": "va:fairfax-county",
  "name": "Fairfax County",
  "kind": "county",
  "fips": "51059",
  "gnis": "1480123",
  "parent": "va",
  "aliases": ["Fairfax Co.", "County of Fairfax"],
  "not_to_be_confused_with": ["va:fairfax-city"],
  "geometry_ref": "commonwealth://jurisdictions/va:fairfax-county.geojson"
}
```

- `kind` enum for V1: `state | county | independent-city | town | school-division | regional-body | authority | special-district`. Towns carry both `parent: va:<county>` and the state chain.
- `id` slugs are stable, lowercase, and never reused. FIPS and GNIS ride along for joins with federal data (Census MCP, NEPA-MCP) but are not the primary key, because not every jurisdiction Commonwealth cares about has one (authorities, some districts).
- `not_to_be_confused_with` is a real field, not documentation: resolution results for either member always mention the other (§ 3.2). Seeded pairs: Fairfax City/County, Richmond City/Richmond County, Roanoke City/Roanoke County, Franklin City/Franklin County, Charles City County (a county, despite the name), Bedford (former city, now town in Bedford County).
- The full jurisdiction table ships as data in the repo (one YAML per jurisdiction, generated initially from Census TIGER + GNIS, then hand-corrected), versioned like source manifests. It is small (a few hundred rows) and load-bearing; treat edits as reviewed changes with tests.

## 2. The tool contract

`registry.resolve_jurisdiction` accepts exactly one of:

| Input | Example | Resolution path |
|---|---|---|
| `name` | "Fairfax" | alias table + fuzzy match over names |
| `address` | "123 Main St, Vienna, VA" | geocode (§ 4), then point-in-polygon |
| `point` | `{lon, lat}` | point-in-polygon against boundary geometries |
| `fips` | "51059" | exact table lookup |
| `zip` | "22180" | ZIP-to-jurisdiction table, often one-to-many |

Passing more than one input is an `InvalidQuery` error naming the conflict, not a silent precedence rule.

### 2.1 Result shape

Standard envelope (design/provenance-envelope.md); `data`:

```json
{
  "resolved": {"id": "va:vienna-town", "kind": "town",
               "parents": ["va:fairfax-county", "va"],
               "basis": "point_in_polygon"},
  "candidates": [],
  "layered_authorities": [
    {"id": "va:fairfax-county", "relationship": "parent-county"},
    {"id": "va:fcps", "relationship": "school-division"}
  ]
}
```

- `resolved` is present only when exactly one jurisdiction matches at the requested confidence. `basis` names the mechanism (`exact_fips`, `exact_name`, `alias`, `point_in_polygon`, `zip_unique`), never a score.
- `layered_authorities` always lists the stack above/around the resolved jurisdiction, because "whose zoning" (the town's) and "whose schools" (the county division's) have different answers at the same coordinates. Domain tools pick from this stack by capability, not by assuming the resolved leaf.

### 2.2 Ambiguity is a first-class result, not an error

When inputs match multiple jurisdictions (`name: "Fairfax"`, a multi-jurisdiction ZIP), `resolved` is null and `candidates` carries each option with its evidence and a `distinguisher` string ("independent city, not the county"). The tool never picks. This is a deliberate response to observed agent behavior: models substitute world-knowledge guesses for literal inputs (the Mapbox "cal academy" case, ../research/README.md part 4 § 8), and Fairfax City/County is exactly the trap they will hit. Bench tasks (design/bench.md) score whether the agent surfaces the ambiguity to the user instead of silently choosing.

Client-interaction note: candidates-in-`data` is the portable mechanism and the V1 default. The 2026-07-28 MRTR pattern (`resultType: "input_required"`) can layer on later for clients that support it; architecture.md decision 0004 records the choice and trigger.

## 3. Postal-city and boundary traps (the test fixtures)

These are the required regression set; each is a named fixture:

1. Mailing address "Alexandria, VA 22310" that is in Fairfax County, not Alexandria City.
2. `name: "Fairfax"` → two candidates, city and county, with distinguishers.
3. "Richmond" → Richmond City vs. Richmond County (opposite ends of the state).
4. A Vienna address → town resolved, county in `layered_authorities`. *(Unbuilt — geocoder-blocked, § 4. The point and name paths into Vienna are tested; the address path this case names is not, and it is the address that carries the trap.)*
5. ZIP 24450 (Lexington + Rockbridge County mix) → candidates, not a guess.
6. Charles City County by name → county, with a `not_to_be_confused_with` note absent (no such city exists; the trap is assuming it does). *(Both halves asserted: `test_jurisdiction.py::test_charles_city_county_is_a_county_not_a_city`. The absence assertion was added 2026-08-28 after review found the test checking only the `kind`.)*
7. A point on the Fairfax City/County boundary line → both as candidates with `boundary_precision` warning. *(Shipped 2026-08-28 as the containing polygon plus a warning naming the neighbour, not candidates; the upgrade needs the when-does-a-warning-become-a-refusal policy call tracked in the GitHub issues. The test pinning today's behaviour: `test_resolve_by_point.py::test_point_near_a_boundary_warns_instead_of_asserting`.)*
8. Bedford: the dissolved-city history (reverted to town, 2013) must not surface a stale `va:bedford-city`. *(No Bedford rows exist in the 14-row seed yet; lands with the full-table generator, the GitHub issues.)*

## 4. Geocoding dependency

Address resolution needs a geocoder, which is a source like any other, registered in the Government Source Registry with provenance:

- Primary: Virginia's state geocoding service (VGIN composite geocoder) where its terms permit automated use. Verified 2026-08-28: the official service overview states no credentials are needed, offers batch geocoding, and publishes no automated-use restriction (../research/README.md part 3 § 9); the manifest records that finding rather than an invented permission.
- Fallback: Census Bureau geocoder (public API, no key).
- The geocoder used appears in `provenance`; a geocode that falls back is a `warnings` entry, because positional quality differs.
- Never a commercial geocoder by default: terms generally forbid storing/deriving, and provenance would leave the public-data story.

## 5. Non-goals

- No national jurisdiction scheme. IDs are `va:*`; the `us:` layer exists only as the implicit parent. Gate G governs any generalization.
- No parcel-level authority determination (which overlay district applies) — that is `commonwealth-geo`'s job using this spec's output.
- No historical boundary reconstruction in V1 (annexations, the Bedford reversion) beyond not serving stale entities; `TemporalState` on jurisdictions is a Phase 2+ question flagged at Gate A.

## 6. Testing hooks

- Fixture set of § 3, run against the boundary geometries that ship rather than against mocks. A mock cannot reproduce a donut-shaped county.
- ~~A property test: every jurisdiction's geometry centroid resolves to
  itself.~~ **Falsified 2026-08-28 and amended.** Run against the real VGIN
  locality polygons, this fails for 4 of 134: Henrico County's centroid
  lands in Richmond City, Henry County's in Martinsville City, Roanoke
  County's in Salem City, and York County's in Gloucester County. Virginia
  excludes independent cities from the surrounding county's polygon, so a
  county enclosing one is a topological donut whose centre of mass sits in
  the hole — a different government; York needs no donut, ordinary
  concavity does it. The amended rule: **a centroid is a label point, never
  a representative interior point, and nothing may use one to decide
  containment.** The shipped test asserts that framing
  (`test_centroid_is_labelled_as_a_label_point`) rather than the false
  property. Evidence: `docs/audits/centroid-property-2026-08-28.json`;
  discussion: source-quirks.md 2.
- A derivation test: the alias table and `not_to_be_confused_with` graph iterate from the jurisdiction YAML registry, never from a hand-typed list in test code.
- Boundary-precision cases assert the warning fires within N meters of a
  shared border. **N = 50 m, and it is a project-chosen screening
  tolerance, not a publisher figure** — VGIN states no positional accuracy
  for the administrative-boundary layer, and inventing one would be a guess
  presented as a measurement. The check is real: a buffered companion query
  runs server-side against the layer's true (unsimplified) geometry, so
  "within 50 m of another jurisdiction" means exactly that. What it cannot
  tell you is how far the published line sits from the legal line, and the
  warning says so.
