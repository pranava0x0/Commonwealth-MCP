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

---

## 12. VGIN's towns layer carries places whose charters are gone

- **Source:** `va-vgin-admin-boundaries` (towns layer)
- **Observed:** 2026-08-30, live, in review
- **Test:** `tests/test_codex_round_3.py::test_a_dissolved_town_has_no_row`

The layer publishes 191 town polygons. Two of them are not towns.
Columbia and St. Charles both appear in Census TIGERweb as **Census
Designated Places** — `FUNCSTAT: 'S'`, a statistical area with no
government — in the current layer and in the 2020 one, and in neither
case as an Incorporated Place.

VGIN's own metadata agrees for one of them without saying so outright:
Columbia carries `GSOURCE: 'T'` (TIGER-derived rather than
locality-submitted) and `LADOPT: 'N'` (no locality has adopted the
boundary).

Both were registered as live governments on 2026-08-29 and removed on
2026-08-30. The generator had seen the evidence and misread it: the run
log recorded "absent from TIGERweb's current Incorporated Places" as a
quirk of Census coverage and worked around it by deriving the parent from
polygon intersection instead. The absence WAS the finding.

**What the code does:** `tools/build_jurisdictions.py` skips any town
Census does not list as an Incorporated Place and prints why, so the
towns half of the table is cross-checked against two sources like the
localities half always was. The two names resolve through their county's
`former_names` — Columbia to Fluvanna County, St. Charles to Lee County —
because the territory reverted to county governance, which is the Bedford
rule one level down.

---

## 13. The locator returns one address as several candidates, and several addresses as several candidates

- **Source:** `va-vgin-composite-locator`
- **Observed:** 2026-08-30, live
- **Test:** `tests/test_codex_round_3.py::test_confident_geocodes_in_one_place_still_resolve`

Two shapes that look identical in the response and mean opposite things.

"127 Center St S, Vienna, VA 22180" returns the same address twice at
score 100, from the address-point element and the road-centerline element,
about 40 m apart. That is one place described twice.

"Cntr Steet Viena VA" returns four matches between 96.45 and 97.12 that
are four different places, two in Vienna town and two in Fairfax County.
Taking the locator's first result there picks one of two governments.

Distance does not separate them: any rounding fine enough to tell Vienna
from Fairfax County also splits the 40 m pair. **What the code does:**
`geo.resolve_location` places every distinct confident coordinate (up to
four) and compares the GOVERNMENTS, resolving when they agree and
returning candidates with `requires_user_choice` when they do not.

The first of those four candidates is addressed FALLS CHURCH and places
into Fairfax County — the postal-city trap turning up inside the
ambiguity check, and one more reason the comparison is on placed
governments rather than on the strings the locator returned.

---

## 14. Twenty incorporated towns cross a county line

- **Source:** `va-vgin-admin-boundaries` (towns layer)
- **Observed:** 2026-08-30, in review
- **Test:** `tests/test_codex_round_3.py::test_towns_that_cross_a_county_line_name_every_county`

Deriving a town's county from a single interior point finds one county
and cannot see that the town extends into another. Twenty of the 191 town
polygons VGIN publishes do: Herndon reaches Fairfax and Loudoun, Farmville reaches
Prince Edward and Cumberland, West Point reaches King and Queen and New
Kent, and Vinton reaches Roanoke County and Roanoke City.

Two governments apply across that ground, which is the thing
this project's jurisdiction model exists to represent, and the table said
one did.

**What the code does:** the generator samples each town's own polygon
rather than one point, and records the extra counties as `also_within`.
They reach `layered_authorities` and **not** the source-selection stack,
deliberately: a name alone cannot say which part of a straddling town is
meant, so querying the second county's sources for "Herndon" would return
records from ground the caller may not have asked about. A coordinate can
say, and point resolution already returns the county that contains it.
`also_within` refreshes on every generator run without `--force`, since
it answers a geometric question the publishers settle rather than an
editorial one.

It cuts the other way at a coordinate. A point in the Loudoun part of
Herndon is not in Fairfax, so listing Herndon's static `parent` there
would name a county that does not contain the point as an authority over
it. Point resolution takes the containing locality from the polygon that
actually holds the coordinate and drops a county parent that contradicts
it; the state above still applies wherever the point is.

## 15. Vienna's current zoning districts are served under a service named "Proposed_Districts"

- **Source:** `va-vienna-town-zoning`
- **Observed:** 2026-09-07, while registering the source
- **Test:** `tests/servers/geo/test_town_sources.py::test_a_point_in_vienna_returns_the_town_and_the_county`

The Town of Vienna's ArcGIS Online organization publishes several zoning
feature services: "TOV Zoning Districts" and "Zoning Districts" from
2019, "Zoning Districts July 2019 Update", and a service named
`Proposed_Districts` whose item is titled "TOV 2024 Zoning". The town's
current zoning map draws the last of these and no other. That web map is
the one the town titles for the districts in effect from 1 January 2024. The name records the ordinance rewrite
the districts were drawn for; the districts were adopted and the service
was never renamed. The older services are still public and still answer
queries, with 2019 districts.

A search that trusts names picks the wrong layer here. The 2026-08-28
search for a Vienna source found the viewer application and stopped; the
service behind it was found by reading the web map's own layer list.

**What the code does:** the manifest names the service the current map
displays and says why in a comment, and the same fact is in its
`known_limitations`, so every envelope that cites the source carries it.
Nothing rewrites the service name.

## 16. ArcGIS Online refuses a long GET with HTTP 414, and answers the same query as a POST

- **Source:** `va-leesburg-town-parcels-zoning`, first; any hosted `services*.arcgis.com` service
- **Observed:** 2026-09-07, recording the Leesburg fixture
- **Test:** `tests/core/test_egress.py::test_a_query_too_long_for_a_url_is_sent_as_a_form_post`

The recording plan looks for a parcel number that the layer publishes as
more than one polygon, and intersects each polygon with the zoning layer.
Leesburg's is `079156879000`, two polygons of 478 vertices each, which is
18 KB of geometry once encoded into a query string. `services1.arcgis.com`
answered the GET with HTTP 414. Fairfax County's own on-premises server had
accepted every polygon sent to it, including larger ones, so nothing had
tripped this before.

**What the code does:** every ArcGIS query operation accepts the same
parameters as a form POST, so `HttpFetcher` sends a query whose encoded
URL would pass 4,000 characters as one. The switch is on length alone:
an ordinary query is still a GET, and a recording is keyed on the URL and
the parameters rather than the method, so no fixture changed. The egress
policy applies to the POST exactly as to the GET; only the request's
shape differs.

## 17. A one-polygon parcel can intersect two zoning districts (a note)

- **Source:** `va-leesburg-town-parcels-zoning`
- **Observed:** 2026-09-07, choosing the sample parcel
- **Test:** none; a note

Parcel `230177709000`, one polygon of 0.24 acres at 209 Old Waterford Rd
NW, intersects two of the town's zoning polygons: MC and R-6. Whether the
parcel straddles the district line or only touches it along an edge was
not determined; an intersection query cannot say, and this project does
not compute overlaps of its own. The sample parcel was changed to one at
310 Catoctin Cir SW that intersects a single district, so the examples
read plainly, and this entry records that the two-district case is real
and near the town centre.

The skill already covers it: `parcel-zoning-screen` step 2 tells the
model to report every district and say the parcel touches more than one,
and that holds whichever geometry is true.


## 18. The Code of Virginia has a keyless JSON API and no full-text search

- **Source:** `va-code-of-virginia`
- **Observed:** 2026-09-08, answering issue #12's first acceptance criterion
- **Re-checked:** 2026-09-09 — unchanged; see the watch below
- **Test:** `VirginiaLawAdapter.search_status()`, reported under
  `search_watch` in this source's health output

Issue #12 asks whether the site's own search is public or keyed before
anything is built. Both halves of the answer turned out to matter.

**The search is public, keyless, and currently down.**
`/Scripts/searchCoV.js` sends the browser to
`https://law.lis.virginia.gov/search_cov?query=<TERMS>+url:/vacode/<title>/<chapter>/<part>/<section>/`.
No key, no token, no session — a plain GET anyone can issue. It answered
three different queries on 2026-09-08 with the same page: "The Search
Appliance is down. Please try again later." A fixture recorded against it
today would record an outage, so `civic.search_law` cannot be built and
verified from this path while that holds.

**There is a JSON API, and it has no search operation.** The developers
page advertises RESTful services in JSON and XML. Its links point at
`/jsonapi/` and `/xmlapi/`, which both serve only the operations page;
the real base is `/api/`, which the operations page gives in each row's
`title` attribute and `href`. Verified working on 2026-09-08, keyless,
`application/json`:

| Operation | Returns |
|---|---|
| `CoVTitlesGetListOfJson` | every title in the Code |
| `CoVChaptersGetListOfJson/{title}` | the chapters in a title |
| `CoVSectionsGetListOfJson/{title}/{chapter}` | the sections in a chapter |
| `CoVSectionsGetSectionDetailsJson/{section}` | one section's full detail |

There is no full-text operation among the twenty-three. A section that
does not exist returns `{"TitleNumber":null,"TitleName":null,"ChapterList":[]}`
with HTTP 200, which is the same "found nothing" shape
`civic.get_code_section` already reports as `found=False` rather than an
error.

**Re-checked 2026-09-09, and watched from now on.** `search_cov` still
answers — publicly, keylessly, HTTP 200 after one redirect — and its
backend still returns "The Search Appliance is down" for every query
tried. Two consecutive days is not a blip, and the endpoint is the
publisher's to fix, not this project's to work around.

Nothing reads that endpoint. What changed is that the manifest now
declares it as `search_url` and the adapter's health output carries a
`search_watch` block saying whether the backend has come back. It is
reported and never graded: both endpoints this project actually reads
are healthy, so a down search appliance is not this source being
unhealthy. The point is that the day it recovers shows up in
`commonwealth sources probe` instead of waiting for someone to
re-try it by hand.

That leaves two consequences, neither of them decided here. Full-text search over the
Code has no working public path today, so #12 cannot be closed as
written. And the structural operations answer the need behind it — a
caller who does not already know the citation — without claiming to be a
search, which is the same naming discipline that made the existing tool
`get_code_section` and not `search_law`. The JSON API would also replace
the HTML parsing behind that tool, which is the fragility #12 lists as
its own caveat.

---

## 19. An SPA answers HTTP 200 for API paths it does not have

- **Source:** `va-lis-legislative-api` (registered as inventory)
- **Observed:** 2026-09-09, answering issue #11's access question
- **Test:** none; there is no adapter to test, which is the finding

The General Assembly's legislative API is key-gated, and establishing
that took more than reading status codes.

`lis.virginia.gov` serves a React single-page app. Any path the app
routes on the client answers **HTTP 200 with the app's own HTML shell**,
whose body says "You need to enable JavaScript to run this app." That
includes paths shaped exactly like endpoints:

| Path | Status | Content-Type | What it is |
|---|---|---|---|
| `Session/api/getsessionlistasync` | 401 | `text/plain` | the real API |
| `Member/api/getmemberlistasync` | 401 | `text/plain` | the real API |
| `Committee/api/getcommitteelistasync` | 401 | `text/plain` | the real API |
| `Bill/api/getbilllistasync` | 200 | `text/html` | the SPA shell |
| `LegislationDetails/api/getlegislationdetailsasync` | 200 | `text/html` | the SPA shell |

A probe that checked status codes would report the bills endpoint as
public and the members endpoint as gated, and conclude this source was
half-open. It is not: the 401s are the API, and the 200s are a web page.

Two things follow for this project. Registering the source means reading
bodies, not codes — `HttpFetcher._decode_json` already refuses a
non-JSON body as "bot challenge or outage page?", which is the same
instinct and would have caught this. And the health-probe vocabulary
should not grow a check that treats 200 as healthy for a source whose
200 is an error page; § 18's `search_watch` matches on the publisher's
own sentence for the same reason.

The API needs a key, the key comes from a registration form a human
fills in, and issue #11 stays open until someone has one.

---

## 20. The legislature publishes bills as bulk CSV, keyless, in inconsistent casing

- **Source:** `va-lis-legislative-api` (registered as inventory)
- **Observed:** 2026-09-10, revising § 19's conclusion about issue #11
- **Test:** none; nothing reads these files yet

§ 19 established that the legislative JSON API is key-gated. That is
still true and it was the wrong thing to stop at: the same division
publishes the same session data as **bulk CSV over Azure Blob Storage,
documented, keyless, and updated hourly during session**.

The help page at `help.lis.virginia.gov/data/` gives the pattern:

```text
https://lis.blob.core.windows.net/lisfiles/<year><session-type>/<FILE>
```

where session type is `1` for a regular session, `2` and `3` for
special sessions — so `20261/BILLS.CSV` is the 2026 regular session's
bills. Verified live for the **current** session, not only historical
ones.

**The file names are not the casing the help page prints.** Azure Blob
is case-sensitive and the container's own casing is inconsistent, so a
client that trusts the documentation 404s on half the files:

| Documented | Actually served | Size (2026 regular) |
|---|---|---|
| Bills.csv | `BILLS.CSV` | 1.3 MB |
| Docket.csv | `DOCKET.CSV` | 78 KB |
| Subdocket.csv | `SUBDOCKET.CSV` | 13 KB |
| Vote.csv | `VOTE.CSV` | 3.9 MB |
| History.csv | `HISTORY.CSV` | 4.7 MB |
| Members.csv | `Members.csv` | 6.7 KB |
| Committees.csv | `Committees.csv` | 1.9 KB |
| Sponsors.csv | `Sponsors.csv` | 1.1 MB |
| Summaries.csv | `Summaries.csv` | 4.3 MB |
| Amendments.csv | `Amendments.csv` | 60 KB |
| CommitteeMembers.csv | `CommitteeMembers.csv` | 6.5 KB |
| SubCommitteeMembers.csv | `SubCommitteeMembers.csv` | 14 KB |
| FiscalImpactStatements.csv | `FiscalImpactStatements.csv` | 325 KB |
| VoteStatements.csv | `VoteStatements.csv` | 372 KB |

`Section.csv` is documented and served under no casing tried.

Container listing is disabled — `?restype=container&comp=list` returns
`ResourceNotFound` — so a client cannot discover the real names. They
have to be known, which is why they are written down here.

**What this changes for issue #11.** The blocker was framed as "a
registration only a human can complete." That is now only true of what
the API carries beyond these files. Bills, votes, sponsors, summaries
and history for the current session are readable today with no key.

It is a different adapter shape from anything registered: a
whole-session snapshot rather than a query service, so answering a
question means downloading a file and filtering it locally. That is
worth distinguishing from the Code of Virginia's missing search (§ 18).
There, the publisher runs no full-text operation and building one would
be this project answering a question the source cannot. Here the
publisher hands over the whole dataset deliberately, and filtering what
they published whole is reading it, not inventing an operation over it.
