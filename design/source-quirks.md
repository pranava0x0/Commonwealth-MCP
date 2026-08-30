# Known source quirks

Real, observed variances in registered government sources — things the
data does that a reasonable person would not predict from the schema.

Rules for this file:

- **Only observed quirks.** Every entry names how it was found and when.
  No "this could happen" entries; those belong in the GitHub issues.
- **Write a test if the quirk changes what the code does**, and list the
  test name here. If there is no test, label the entry a note.
- **Do not quietly work around a publisher's quirk.** Report what the
  source actually returned. Smoothing it over makes the data look
  cleaner than it is, and the next person cannot tell the difference.

Each entry says what the quirk is, where it lives, why it matters, and
what the code does about it.

---

## 1. VGIN administrative boundaries: Prince George County ships as two polygons

- **Source:** `va-vgin-admin-boundaries`, `localities` layer
- **Observed:** 2026-08-28, live
- **Test:** `tests/servers/geo/test_geo_boundaries.py::test_split_polygon_locality_returns_both`

The layer carries **134 rows for Virginia's 133** counties and independent
cities. Prince George County (FIPS `51149`, GNIS `1480160`) is published as
two separate features sharing both identifiers: a 281.02 sq mi body
(`OBJECTID:73`) and a 0.0076 sq mi sliver (`OBJECTID:72`). Their
`LASTUPDATE` values differ, so this is not an accidental exact duplicate.

**Why it matters:** any code that assumes "one FIPS, one polygon" either
crashes or silently discards one of two official records. Area sums double
count. A `[0]` index picks the sliver about half the time, depending on
result ordering.

**What the code does:** `geo.find_boundaries` returns **both**, each with
its own evidence ref, and attaches a note saying two polygons carry the
identifier and none was picked as the real one. Nothing dedupes.

---

## 2. Virginia counties that enclose an independent city are topological donuts, so their centroids fall in another government

- **Source:** `va-vgin-admin-boundaries`, `localities` layer
- **Observed:** 2026-08-28, live, all 134 polygons checked
- **Evidence:** `docs/audits/centroid-property-2026-08-28.json`
- **Test:** `tests/servers/geo/test_geo_boundaries.py::test_centroid_is_labelled_as_a_label_point`

jurisdiction-resolution.md § 6 proposed the property test *"every
jurisdiction's geometry centroid resolves to itself."* Run against the real
geometries, **it fails for 4 of 134 localities**:

| Locality | Centroid actually lands in | Why |
|---|---|---|
| Henrico County | Richmond City | county wraps the city on three sides |
| Henry County | Martinsville City | county encloses the city |
| Roanoke County | Salem City | county encloses the city |
| York County | Gloucester County | deeply concave around the York River |

Virginia's independent cities are **excluded** from the surrounding
county's polygon, so those counties are rings with a hole in the middle,
and a centre of mass lands in the hole — a different government. York is
not even a donut; ordinary concavity was enough.

**Why it matters:** "centroid" reads like "a point inside this place". For
these four it is a point inside a *neighbour*. Using a centroid as a
representative point would silently attribute Henrico County questions to
Richmond City.

**What the code does:** the centroid is surfaced (it is a useful label
point for map placement) but every one carries an inline note saying it is
not guaranteed interior and must never be used for containment. Nothing in
the codebase uses a centroid to decide which jurisdiction contains a place;
containment goes through a real point-in-polygon query.

**Design correction:** the property test in
jurisdiction-resolution.md § 6 is amended rather than implemented as
written. See that section.

---

## 3. VGIN boundary layers publish no layer-level edit date, but every feature carries its own

- **Source:** `va-vgin-admin-boundaries`, both layers
- **Observed:** 2026-08-28, live
- **Test:** `tests/servers/geo/test_geo_boundaries.py::test_record_vintage_survives_absent_layer_vintage`

`editingInfo` is absent on both layers, so the adapter's usual freshness
path yields `source_updated_at: null` and the envelope raises
`freshness_unavailable` — correct, and the same shape as VGIN's parcels
layer. But each feature has a populated `LASTUPDATE`.

**What the code does:** `geo.find_boundaries` maps `LASTUPDATE` and emits
it per record as `record_updated_at` (epoch ms converted to ISO). The
envelope still says the *layer* vintage is unknown, because it is; the
record vintage is reported separately and is not promoted to stand in for
it.

---

## 4. ArcGIS `distance` buffering is exact, but proximity results are easy to misread

- **Source:** `va-vgin-admin-boundaries` (any ArcGIS layer with
  `supportsQueryWithDistance`)
- **Observed:** 2026-08-28, live
- **Note only** — no defect; recorded because it was initially mistaken for one.

A buffered point query at Fairfax City's approximate centre returns
**Fairfax County** at `distance=40m` and above, which looks wrong for a
point over a kilometre from the county line. It is correct: Fairfax County
retains an **enclave inside Fairfax City** (the county courthouse
complex), and Fairfax City's polygon has a matching hole — hence its
`ring_count: 2`. The threshold sits between 20 m and 40 m.

**Why it is recorded:** the first reading of this result was "the platform's
distance parameter is unreliable, don't build on it." That conclusion would
have been wrong and would have cost the boundary-straddle warning. Verify
against the geometry before declaring a platform broken.

**What the code does:** `registry.resolve_jurisdiction` uses a buffered
companion query at a **project-chosen** 50 m tolerance to flag points near
another jurisdiction's line. The tolerance is not a publisher accuracy
figure — VGIN publishes none for this layer — and the code and the warning
both say so.

---

## 5. ArcGIS rejects a quoted literal against a numeric column, with a message that names nothing

- **Source:** `va-vgin-address-points` (`ZIP_5`), `va-vgin-landmarks`
  (`FIPScode`)
- **Observed:** 2026-08-29, live
- **Test:** `tests/adapters/test_arcgis_unit.py::test_numeric_fields_are_sent_unquoted`

`ZIP_5 = '24450'` fails. `ZIP_5 = 24450` succeeds. The failure arrives as
HTTP 200 carrying `{"error": {"code": 400, "message": "Unable to complete
operation.", "details": ["Unable to perform query operation."]}}` — no
field name, no type, nothing pointing at the quoting.

It is not consistent across the registry either, which is what makes it a
trap rather than a rule to memorise: VGIN's parcels layer stores `FIPS` as
text and its landmarks layer stores `FIPScode` as an integer, so the same
canonical `fips` filter needs different SQL depending on which layer it
lands on.

**What the code does:** `LayerDecl.numeric_fields` names the canonical
fields whose source column is numeric, so the layer's schema stays in the
manifest and a caller passing `"51059"` never has to know. The adapter
also takes a real Python `int` or `float` at its word; a string that
merely looks numeric is still escaped and quoted.

---

## 6. `returnDistinctValues` and `resultRecordCount` are mutually exclusive on VGIN's address points

- **Source:** `va-vgin-address-points`
- **Observed:** 2026-08-29, live
- **Test:** `tests/adapters/test_arcgis_unit.py::test_distinct_queries_drop_the_row_cap`

The same DISTINCT query succeeds without `resultRecordCount` and fails
with it, again as HTTP 200 with error 400 and no detail. Since the row cap
is how every other query here stays bounded, dropping it is not free.

**What the code does:** the adapter removes `resultRecordCount` when
`distinct_fields` is set, and the discipline that replaces it is that a
distinct query must be over a low-cardinality field. `geo.resolve_location`
uses it for one thing only — which localities carry a ZIP — where the
answer is at most a handful of rows out of millions. The egress byte cap
is the backstop if that discipline is ever broken.

---

## 7. Building footprint area is published in Web Mercator, where it is not ground area

- **Source:** `va-vgin-building-footprints`
- **Observed:** 2026-08-29, live
- **Test:** `tests/servers/geo/test_find_buildings.py::test_area_is_never_returned_as_a_bare_number`

`Shape__Area` is real and the service even labels its units
(`geometryProperties.units: esriMeters`), which is exactly what makes it
misleading: the layer's spatial reference is EPSG:3857, where area is
inflated by sec squared of the latitude. At 38 degrees north that is about
1.61x. A caller who reads the number as square metres of roof overstates
every building by more than half.

**What the code does:** the publisher's value is returned unconverted
under `footprint_area_web_mercator_sq_m`, whose name says which projection
it is in, alongside `footprint_area_sq_m_approx` derived from the query's
own latitude and declared in the envelope's `transformations`. Neither is
presented as the other.

---

## 8. VGIN's landmark service has no layer 0

- **Source:** `va-vgin-landmarks`
- **Observed:** 2026-08-29, live
- **Test:** `tests/servers/geo/test_find_landmarks.py::test_the_registered_layer_id_is_one_not_zero`

Layer 1 is `Virginia Landmark Locations`. Layer 0 returns
`{"error": {"code": 500, "message": "json", "details": []}}` — a 500 with a
one-word message, not a 404. Every other layer registered here is 0 or a
small numbered set starting at 0, so a manifest copied from the parcels
one and left at `layer_id: 0` would look right and fail at the first
query with an error that reads like an outage.

---

## 9. Landmark records are other agencies' records, and many have never been re-checked

- **Source:** `va-vgin-landmarks`
- **Observed:** 2026-08-29, live
- **Test:** `tests/servers/geo/test_find_landmarks.py::test_each_record_names_the_organisation_it_came_from`

Each landmark carries `Src` and `SrcTyp` naming where it came from — DCJS
for a police station, DOE for a public school, USPS for a post office,
"Agency" for others. The registered publisher is an aggregator here, and
for any one record the authority is whoever `Src` names.

`LastCheck` is null on a substantial share of records; one of the four
around Vienna has none. The layer publishes no layer-level edit date
either, so there is no date to fall back to — and falling back would claim
a verification that never happened.

**What the code does:** `geo.find_landmarks` returns `source_organization`
and `source_type` on every record with an `authority_note` saying the
record is that organisation's, and a null `LastCheck` produces an explicit
"the publisher has no verification date" note rather than any date at all.
Record `URL` values are returned as data and never fetched; a test asserts
no record URL appears in the fetcher's call log.

---

## 10. A publisher's website can refuse a request its GIS service answers

- **Source:** `va-deq-water-quality-stations`
- **Observed:** 2026-08-29, live
- **Note only** — recorded because it changes how a terms review ends,
  not what any code does.

`apps.deq.virginia.gov`'s ArcGIS REST directory answers anonymously and
the service declares `copyrightText: "Virginia DEQ"` and capabilities
`Query,Map,Data`. `www.deq.virginia.gov/terms-of-use` returns an Akamai
"Access Denied" 403 to a plain HTTP GET, and so does
`/our-programs/data`. The agency's data is reachable and its terms are
not.

DEQ's 97 datasets on the Virginia Open Data Portal do not close the gap
either: none carries a license field.

**What the code does:** `Access.terms_gap` holds what a review could not
establish, and every envelope citing that source carries a `terms_note`
warning quoting it. A gap recorded only in YAML is a caveat a contributor
reads once; this makes it a disclosure at the point of use. Richmond's
recorded terms gap uses the same field.

---

## 11. A town borrows its county's FIPS, so a FIPS-keyed layer cannot be narrowed to a town

- **Sources:** every registered layer keyed on FIPS
  (`va-vgin-road-centerlines`, `va-vgin-address-points`,
  `va-vgin-landmarks`, `va-vgin-statewide-parcels`)
- **Observed:** 2026-08-30, in review
- **Test:** `tests/test_codex_round_2.py::test_a_town_query_says_when_it_was_widened_to_the_county`

Virginia's incorporated towns have a place FIPS and no county FIPS of
their own: Vienna is `place_fips: 81072`, and the only county code
available to it is Fairfax County's `51059`. So a jurisdiction filter
built from the stack walks past the town and lands on the county.

The filter is still right to apply. It is a correct superset — everything
in Vienna is in Fairfax County — and it is what stops a locality-scoped
identifier matching another locality's record on a statewide layer, which
was a real false hit before the filter existed. What is wrong is
reporting the result under the town's name: a `find_roads(jurisdiction=
"Vienna")` answer scoped to Fairfax County returned 39 county-wide
segments where the town has a handful.

The two registered road sources make the difference visible in one call.
VDOT's route master keys on the jurisdiction NAME, so "Town of Vienna" is
the town and it returns 2 routes; VGIN's centerlines key on FIPS and
return 39.

**What the code does:** `_jurisdiction_scope()` returns the filter *and*
the jurisdiction it actually reaches. When those differ, the answer
carries a `widened_scope` note naming both — "this source has no key for
Vienna (town), so the query was narrowed to Fairfax County instead". A
source whose scope is exact says nothing, so the note stays meaningful.
