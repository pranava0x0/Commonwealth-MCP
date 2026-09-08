# What each source cost to onboard

`design/architecture.md` § 38.13 asks for a record, kept from the first
milestone, of what adding a source costs: time spent, and whether server
or CLI code had to change.

The claim it tests is that adding a source should mostly be configuration.
If that is true, the share needing code changes should fall toward zero.
It has not yet, and the reason is worth reading rather than the number
alone: every code change so far has been a single-source assumption that a
second source shape exposed. Those are real bugs found by real data, and
they run out.

One row per registered source, newest first. "Code change" means server,
adapter, or CLI code — a manifest is not a code change, and neither is a
test.

| Source | Registered | Code change | What it was |
|---|---|---|---|
| `va-vienna-town-zoning` | 2026-09-07 | Yes | The first zoning-only source. `geo.find_zoning` answered a parcel number by reading the source's own parcel layer, and a town with no parcel layer has none to read; it now borrows the polygon from a parcel source above the town in the stack and names whose it was. The sampler got a zoning-only recording plan that records the county's answers alongside the town's. This is the change the town slot of the forcing set existed to find. |
| `va-leesburg-town-parcels-zoning` | 2026-09-07 | Yes | Two changes, neither in the adapter's model of a layer. ArcGIS Online refused a 478-vertex parcel polygon in a GET with HTTP 414, so the fetcher sends a query whose URL would pass 4,000 characters as a form POST (design/source-quirks.md § 16). And the statewide cross-check plan skipped every town, because a town has no FIPS of its own; it walks up to the county's now, as the tools already did. The manifest itself is Fairfax's shape and needed nothing new. |
| `va-deq-water-quality-stations` | 2026-08-29 | **No** | First MapServer and first non-VGIN, non-locality publisher. The adapter, written against FeatureServer, needed nothing. `Access.terms_gap` was added, but for the disclosure rule rather than for this source's shape. |
| `va-vdot-lrs-routes` | 2026-08-29 | Yes | `LayerDecl.jurisdiction_scope` mode `jurisdiction_names`: the layer's jurisdiction key is VDOT's own numbering, not FIPS, so scoping by name was the only correct option. |
| `va-vgin-road-centerlines` | 2026-08-29 | Yes | `where_any_of` in the adapter, and `jurisdiction_scope` mode `fips_any_of`: a segment carries FIPS on each side, so "in this locality" is a disjunction the adapter could not express. |
| `va-vgin-landmarks` | 2026-08-29 | Yes | `LayerDecl.numeric_fields`: `FIPScode` is an integer here and text on every layer registered before it, and ArcGIS rejects a quoted literal against a numeric column with a message that names nothing. |
| `va-vgin-building-footprints` | 2026-08-29 | Yes | `LayerDecl.value_labels` for the publisher's own coded-value domain, and the Web Mercator area conversion in `geo.find_buildings`. |
| `va-vgin-composite-locator` | 2026-08-29 | Yes (expected) | A whole new adapter type. A GeocodeServer is a different request and response from a FeatureServer query; this was never going to be configuration. |
| `va-vgin-address-points` | 2026-08-29 | Yes | `where_prefix` and `distinct_fields` in the adapter, plus numeric-literal handling for `ZIP_5`. |
| `va-vgin-admin-boundaries` | 2026-08-28 | Yes | Three adapter features: server-side generalization, platform centroids, metric proximity buffering. |
| `va-charles-city-county-parcels` | 2026-08-28 | Yes | Surfaced a CLI single-source assumption (every manifest has a zoning layer). |
| `va-vgin-statewide-parcels` | 2026-08-28 | Yes | Surfaced a CLI single-source assumption (the fixture pool only ever loaded Fairfax's). |
| `va-code-of-virginia` | 2026-08-28 | Yes (expected) | A whole new adapter type (HTML). |
| `va-richmond-city-parcels-zoning` | 2026-08-28 | Yes | Adapter extension: per-layer `service_url`, because Richmond splits parcels and zoning across two services. |
| `va-fairfax-parcels-zoning` | 2026-08-27 | n/a | The first source; there was nothing to be a change to. |

Inventory-only manifests (`va-vdh`, `va-open-data-portal`,
`va-eva-procurement`, `va-scc`, registered 2026-08-29) are not in the
table. They describe no endpoint, so there is nothing for them to cost.
The `none` adapter type and the activation gates around it were code, and
they were written once for the shape rather than per row.

## What the count says so far

Thirteen onboardings, two of which were new adapter types where a code
change was the point. Of the other eleven, nine needed code and two did
not.

The two town rows, from 2026-09-07, are the first in which the change
was not to the adapter's model of a layer. Leesburg's manifest is
Fairfax's shape and validated first time; what moved was the transport
(a request too long for a URL) and a recording plan (a town has no FIPS).
Vienna's change was to a tool: a zoning source with no parcel layer had
no way to answer a parcel number, and the forcing set's town slot was
kept open for exactly that kind of finding. The layer model held for both,
which is the trend the count is meant to show.

Both of the two are from 2026-08-29 and both are informative. DEQ is the
stronger signal: a different agency, a different host, a different service
type, and the adapter did not move. The other, `va-vgin-landmarks`,
needed only a one-field declaration.

The 2026-08-29 changes also differ in kind from the earlier ones. The
2026-08-28 changes were bugs — code that assumed one source and broke on
the second. The 2026-08-29 changes are declarations: `numeric_fields`,
`value_labels`, `jurisdiction_scope` all move a fact about a layer out of
code and into the manifest, which is the direction the metric is supposed
to be measuring. A source registered after them can use all three without
touching Python.

So the count is not yet falling, and the reason it has not is visible in
the rows: the adapter's model of "a layer" was built from one publisher's
layers and has been growing to fit real ones. The next few sources are
the test of whether it has stopped growing.

## How to add a row

Append after each onboarding, with the date and one sentence on the
change. If nothing in `src/` moved, write **No** — that is the result
worth recording.
