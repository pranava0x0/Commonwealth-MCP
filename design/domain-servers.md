# Spec: Domain Servers and Tool Contracts (V1: registry, geo, civic)

**Plugs into:** architecture.md § 7 (Server Boundaries), § 27 (Tool Contract Guidelines), § 15 (Toolsets)
**Status:** Draft for review. Tool names below are proposals; each tool's full contract page is generated into docs/reference/ once code exists.
**Why this exists:** The design spec names the servers and sketches tool lists; this spec fixes the conventions every tool follows and trims V1 to contracts that can actually be built against Phase 1 sources. The survey's tool-design taxonomy (../research/README.md part 3 § 3) shapes the split: semantic composites at the user surface, composable primitives beneath, both exposed.

---

## 1. Conventions (all tools, all servers)

1. **Naming:** `domain.verb_noun`, lowercase; verbs from a short controlled list (`resolve`, `find`, `search`, `get`, `screen`, `intersect`, `buffer`, `query`). `find` returns entities by criteria; `search` is text-forward; `get` takes an exact ID; `screen` returns constraint findings with explicit screening-only framing.
2. **Arguments:** semantic, few, typed. `jurisdiction` accepts names, FIPS, or `va:` IDs and resolves through the jurisdiction model everywhere it appears — one resolution code path, not per-tool parsing. `location` accepts address | point | parcel-ref uniformly. Date ranges are `{from, to}` ISO dates, never platform-specific formats. No vendor pass-through parameters on semantic tools (architecture.md § 27's `where`/`outFields` ban).
3. **Every response is the envelope** (design/provenance-envelope.md), concise by default; `detail: "full"` opts into more per Anthropic's measured concise/detailed guidance.
4. **Descriptions follow a template**, moved here 2026-09-02 from the docs-practices spec that was folded into CONTRIBUTING: one line on what the tool does; when to use it and when NOT, naming the better tool; argument notes with Virginia-specific examples ("jurisdiction accepts names, FIPS, or `va:` IDs; Fairfax City and Fairfax County are different places"); and a result-shape note naming the envelope. Descriptions are versioned with the tool contract and covered by Tier-2 bench tasks, so a description edit that hurts selection shows up as a regression rather than as a mood.
5. **Error strings are documentation too.** Each names the failure class, what it means in government-data terms, and the next move (design/provenance-envelope.md § 7 has the pattern). They are read by a model under pressure, which is a harder audience than a developer with a debugger.
6. **Ordering:** tool registration order is explicit and stable per server (contract-tested), for prompt-cache friendliness.
7. **Deprecation aliases from day one:** the alias table exists (empty) in core; renames are additive with aliases, per the github-mcp-server mechanism.
8. **Toolsets:** each server declares `default` (the small daily-driver set) plus named extras; `discovery` (registry tools) and `spatial` (geo primitives) stay out of `default` per architecture.md decision 0001. As built (recorded 2026-08-28): one registry tool, `registry.resolve_jurisdiction`, rides in `default` via a `discovery-min` toolset — every skill walk's step 1 is resolution (design/skills.md § 2), and the meta-tool selection hazard 0001 guards against lives in the search/describe/status tools, which stay out. A refinement of 0001's letter, not its reasoning. Ratified 2026-08-29 as a dated amendment to decision 0001, which also records what would change it back (a Tier-2 sweep showing the tool called when the question did not need it).

## 2. `commonwealth-registry` (toolset: `discovery`)

| Tool | Contract sketch |
|---|---|
| `registry.resolve_jurisdiction` | jurisdiction-resolution.md § 2, in full |
| `registry.search_sources` | text + jurisdiction + capability filters over manifests; returns manifest summaries with lifecycle/authority; proposed sources included, labeled |
| `registry.describe_source` | one manifest, formatted for reading, terms and limitations prominent |
| `registry.source_status` | health/degraded state, last-verified, recent probe history |

`find_authoritative_source` from the design spec folds into `search_sources` (an `authoritative_only` flag) rather than being a separate tool — one search surface, fewer near-duplicate choices for the model. `list_capabilities` becomes a resource (`commonwealth://capabilities`), not a tool: it's static vocabulary, exactly what resources are for. (Neither is built as of 2026-08-28: `search_sources` takes text/jurisdiction/capability only, and no MCP resources are registered anywhere — the vocabulary ships as `sources/capabilities.yaml` alone. Both stand as the contract for when they land.)

## 3. `commonwealth-geo`

Composites (in `default`): `geo.resolve_location`, `geo.find_parcel`, `geo.find_zoning`, `geo.find_boundaries`.
Primitives (toolset `spatial`): `geo.intersect`, `geo.buffer`, `geo.find_nearby`, `geo.query_source` (the registered-source escape hatch, architecture.md § 12.2).

- Primitives follow osmmcp's five principles verbatim (uniform parameter names, single responsibility, output-as-input compatibility, no side effects, precise errors); the checklist lives in the geo package docstring and reviewers apply it.
- Composites follow architecture.md decision 0005 as **Chosen (architect override, 2026-08-26)**: no ranking, no mode parameter. A composite queries the **top two known-authoritative sources** for the capability in the resolved jurisdiction (`authority_level` decides which two, never a single winner) and always surfaces the per-source results — agreement or conflict — in `data`, with both sources in `provenance`. Where only one registered source exists, one is queried and coverage says so.
- `find_zoning` and friends return the district plus overlay/floodplain flags *as findings with `next_actions`*, never as conclusions; the screening-only warning is structural (envelope § 5), not prose goodwill.
- Geometry in results: simplified inline, full behind a resource, always 4326 (design/adapters.md § 3).
- V1 geo sources, as registered (corrected 2026-08-28; the original line predated the 0005 override and the revised § 6 seed set): VGIN statewide parcels, VGIN administrative boundaries, Fairfax County, Richmond City, and Charles City County, all via `arcgis`. The forcing set's incorporated town is still open and Loudoun follows after it (design/source-registry.md § 6). Routing is the top-two rule above — there is no authority table and no locality-first default (architecture.md decision 0005, Chosen).

**`geo.find_boundaries` shipped 2026-08-28** against a new statewide
source (VGIN Administrative Boundaries, `boundary.lookup`). It follows the
geometry rule above as far as the missing piece allows: geometry is
server-side generalized to 0.0002 degrees and returned only at
`detail: "full"`. The result store that holds the unsimplified polygon was
built 2026-09-02 (decision 0013; #33), so `detail: "full"` now also
returns a handle to the publisher's own rings. Concise —
the default — returns bbox, centroid, area, and vertex counts, which keeps
it inside the envelope's 2000-token data budget. The same source backs
point-in-polygon jurisdiction resolution
(design/jurisdiction-resolution.md § 2), so one onboarding closed two
milestones. Two real publisher quirks it surfaced are recorded in
source-quirks.md rather than normalized away.

**`geo.resolve_location` shipped 2026-08-29.** The geocoder prerequisite
it was blocked on is registered (`va-vgin-composite-locator`, capability
`geocode.address`) and the tool is in `default`. It takes exactly one of
`address` or `zip_code` and refuses both together, because there is no
precedence rule between them and preferring one silently would hide a
contradiction between what the caller typed and where it points. A bare
five-digit ZIP passed as `address` routes to the ZIP path rather than
being refused.

The two paths answer differently on purpose. An address goes to the
locator; a ZIP goes to the address-point layer's DISTINCT query over ZIP
and FIPS, because the locator answers a ZIP with one centroid and a ZIP
spanning several localities has no centre worth returning. Address-based
and ZIP-based jurisdiction resolution (jurisdiction-resolution.md § 2)
ship with it.

The `spatial` primitives (`intersect`, `buffer`, `find_nearby`,
`query_source`) remain unbuilt as of 2026-09-01.

### Tools shipped without a contract entry here (written 2026-09-01)

These five were built between 2026-08-29 and 2026-08-31 and reached code,
toolsnaps, and architecture.md § 15's budget table without an entry in
this spec, which is the document their source comments cite. Written from
the shipped signatures rather than from intent, so an entry that wants
behaviour the code lacks is contract drift and gets its own issue.

| Tool | Toolset | Capability, and the source that answers it |
|---|---|---|
| `geo.find_address` | `default` | `address.lookup` — `va-vgin-address-points` |
| `geo.find_buildings` | `default` | `building.lookup` — `va-vgin-building-footprints` |
| `geo.find_environmental_sites` | `default` | `environmental_site.lookup` — `va-deq-water-quality-stations` |
| `geo.find_landmarks` | `spatial` | `landmark.lookup` — `va-vgin-landmarks` |
| `geo.find_roads` | `spatial` | `road.lookup` — `va-vdot-lrs-routes` and `va-vgin-road-centerlines` |

**`geo.find_address(jurisdiction, address="", lon=None, lat=None)`.**
Exactly one of `address` or a lon/lat pair; a point needs both halves.
The string path is a prefix match on the publisher's own spelling, not a
fuzzy search, so a typed address that needs interpreting belongs in
`geo.resolve_location`. Both paths are scoped to the resolved
jurisdiction's FIPS, because the point path's buffer reaches far enough to
pull in a neighbouring locality's address points while the envelope still
reports the one jurisdiction that was asked for. A record's `po_name` is
a postal city and is never the government: a Fairfax County address reads
"ALEXANDRIA", and `locality` and `fips` are the fields that answer who
governs. Empty means this publisher holds no record, not that no such
address exists.

**`geo.find_buildings(jurisdiction, lon=None, lat=None, pin="",
radius_meters=250)`.** Exactly one of `pin` or a lon/lat pair. On the PIN
path the parcel polygon defines the intersection, so the parcel source
that drew that boundary is in `provenance` and its evidence id is on every
record — with more than one parcel source selectable, a caller otherwise
cannot tell which boundary produced the answer.

Footprint area is published in Web Mercator, where area is inflated about 1.6x at Virginia's
latitudes; both the publisher's figure and a converted approximation are
returned, each labelled. Height, storey, and class fields are frequently
null, which means the publisher has no value rather than zero. A dense
urban query truncates at 25 records with a `truncated_inline` warning; the
handle to the full set waits on the result store (decision 0013, GitHub
issue #33). Empty is not evidence of vacant land — coverage of this
derived layer varies by locality.

**`geo.find_environmental_sites(jurisdiction, lon=None, lat=None,
radius_meters=1609)`.** A point is required and the tool refuses without
one: the registered layer is organised by watershed and carries no
locality field, so a jurisdiction-only query would return every station in
Virginia under a heading naming one county. The radius default is one
mile, the distance a property screening conventionally asks about. What
is registered is DEQ's water-quality monitoring network alone — air,
waste, and land programmes are not in it — so this is a screening input
and never a determination that a site is safe, contaminated, or suitable
for a use. Historic stations are included, which is what `last_sample_date`
is for. Empty means no station of that kind is on record near the point.

**`geo.find_landmarks(jurisdiction, name="", place_type="", lon=None,
lat=None, radius_meters=1000)`.** At least one of `name`, `place_type`, or
a point; an unbounded query would return every landmark in the
jurisdiction. `place_type` is the publisher's own vocabulary, passed
through rather than mapped onto one of ours. Each record names the
organisation it came from, and that organisation is the authority for it,
not the map publisher. Record URLs are returned as data and are never
fetched, because the egress allowlist is per-manifest and following a
record's link would drive through it. A place missing from the layer may
never have been added, so empty never means there is no school there.

**`geo.find_roads(jurisdiction, street_name="", lon=None, lat=None,
radius_meters=100)`.** Exactly one of `street_name` or a point. Two
official sources answer this and they are expected to disagree: VDOT's
route inventory is a linear-referencing model with its own route names and
measures, and VGIN's centerlines aggregate local submissions at segment
detail. Both are returned unreconciled with a comparison block saying
whether the names agree, per the top-two rule above — a difference is
usually a difference in how the road is modelled rather than an error.
Centerlines are not right-of-way boundaries. A road running along a
locality line belongs to both localities in the results.

## 4. `commonwealth-civic` (second milestone — after the geo vertical's beta exit)

Re-sequenced 2026-08-26: the review is right that proving one complete path beats two half-built domains, so civic starts after the geo vertical ships (architecture.md Part 2 review round 2 § 6). The contracts below stand as the target.

`default`: `civic.search_legislation`, `civic.get_bill`, `civic.search_law`, `civic.search_meetings`.
Extras (toolset `civic-full`): `civic.get_vote`, `civic.get_agenda_item`, `civic.search_regulations`.
Deferred beyond V1 (contracts drafted when their sources onboard): campaign finance, election results — both need source-terms review before any contract is worth writing.

- `get_bill` returns status as of retrieval with LIS's own timestamps; bill version identity (introduced/engrossed/enrolled) is explicit in the result, because conflating versions is the domain's classic error.
- `search_law` (Code of Virginia) results carry section citations and effective dates; amendments-pending surfaces as a warning when LIS shows a bill touching the section, which is the cross-tool join the two V1 skills exercise.
- Meetings: Phase 1 covers the localities whose agenda platforms have registered manifests (legistar adapter lands here); coverage honesty does the rest.

**First slice shipped 2026-08-28, ahead of the LIS bill-tracking surface:**
`civic.get_code_section` — direct Code of Virginia citation lookup, not
`search_law`. LIS's own JSON/XML API (bills, members, full-text search)
needs an API key this project hasn't registered for (the GitHub issues); the
public HTML pages at law.lis.virginia.gov don't. The tool reads those
pages directly (a new `virginia_law` adapter type, `html.parser`-based,
no new dependency) rather than waiting on the key. It is named for what
it actually does — direct citation lookup — not `search_law`, since
there is no full-text search behind it; the design sketch's name would
overclaim. `search_law`, `get_bill`, and the rest of the civic default
toolset stay on the LIS-key-registration prerequisite named in
the GitHub issues.

## 5. What deliberately does not exist in V1

Finance, infrastructure, environment, people servers stay at design-spec sketch level; their tool lists are not contracts yet, and writing them before their sources are registered would freeze guesses (data assumptions are guesses until the data is queried). The design spec's lists remain the shape for those phases; each gets a contract page in this spec's format when its Phase begins. NEPA-MCP federation covers the environmental screen in the meantime via the external-catalog entry (design/hub-catalog.md § 1).
