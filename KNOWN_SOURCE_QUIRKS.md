# Known source quirks

Real, observed variances in registered government sources — things the
data does that a reasonable person would not predict from the schema.

Rules for this file:

- **Only observed quirks.** Every entry names how it was found and when.
  No "this could happen" entries; those belong in backlog.md.
- **A quirk that affects behaviour has a test.** The test name is listed.
  A quirk with no test is a note, and it says so.
- **Publisher-side quirks are not bugs to fix silently.** The project's
  job is to surface them accurately, not to normalize them away and make
  the source look tidier than it is.

Each entry: what, where, why it matters, what the code does about it.

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

design/jurisdiction-resolution.md § 6 proposed the property test *"every
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
design/jurisdiction-resolution.md § 6 is amended rather than implemented as
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
