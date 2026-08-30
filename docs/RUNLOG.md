# Run Log

One entry per significant work session or delegated research task: why it
ran, cost where relevant, and whether it was worth it.

## 2026-08-29 — eleven sources, the full jurisdiction table, four drifts closed

Fifteen issues in one session: #2-#9 (sources), plus #14, #17, #21, #22,
#25, #30, #32. 247 tests to 364. `doctor --live` green across 17
manifests. [PR #38](https://github.com/pranava0x0/Commonwealth-MCP/pull/38).

**Sources.** Seven new registrations with a tool each — the VGIN
composite locator (`geo.resolve_location`), address points, building
footprints, landmarks, road centerlines, VDOT's LRS route master, and
DEQ's water-quality stations — plus four inventory-only manifests so the
registry's proposed/active split stops reading as zero coverage debt.

Four times the live data corrected the plan, and each is worth more than
the source it came with:

1. **The issue specifying the address source was wrong about a field.**
   It described `PLACENAME` as the postal place and said to map it as
   one. Read live, `PLACENAME` holds facility names ("Rose Hill
   Elementary School", "ABC Store 099") and is empty for ordinary
   addresses; the postal city is `PO_NAME`. Mapping it as written would
   have put a school's name in the field the tool's own warning tells
   callers to distrust.
2. **The plausible-sounding VDOT service is the derived one.**
   `VA_Primary_and_Secondary_Roads` sounds like the operating agency's
   network and is a republished Census TIGER extract — TIGER field names,
   9,344 features statewide. `LRS_Route_Master`, whose name suggests an
   internal system, is VDOT's own 196,896-route inventory. Field names
   are a provenance fingerprint and they were the only thing that said
   which was which.
3. **VGIN's road service publishes four layers and one dataset.** Layers
   4 and 5 are the same 659,179 segments at two map scales; 1 and 2 are
   road-class subsets. Registering a subset and calling it "roads" would
   have excluded 585,000 local roads.
4. **Building footprint area is published in a projection that inflates
   it.** `Shape__Area` carries `units: esriMeters`, which is true and is
   what makes it dangerous: the layer is Web Mercator, where area is
   inflated ~1.61x at Virginia's latitude. Returned unconverted under a
   field name that says which projection, alongside a converted
   approximation with the latitude it used declared in
   `transformations`.

**The jurisdiction table stopped being a seed.** 14 rows to 325 — all 133
counties and independent cities, all 191 towns, generated from VGIN's
boundary layer and Census TIGERweb, which agreed on all 133 with zero
differences. Town parents are derived by containment against the locality
polygons using TIGERweb's guaranteed-interior points, not centroids: the
centroid property this project already falsified for counties would have
been exactly the wrong tool. 189 derived cleanly. Columbia straddles the
Fluvanna/Goochland line and the generator declined to pick; Columbia and
St. Charles are both absent from TIGERweb's current Incorporated Places
while VGIN still publishes their polygons, which is why they had no
interior point at all.

Trap 8 closed with a new `former_names` field. Three Virginia cities gave
up their charters and became towns (South Boston 1995, Clifton Forge
2001, Bedford 2013), so "Bedford City" now resolves to `va:bedford-town`
with `basis: former_name` and an `alias_match` warning — an enum value
the codebase had and nothing emitted. Seven of the resolution spec's
eight named traps are regression tests now; only the one with an open
policy question (#26) is not.

**Two ways a green suite lied**, both written up in
`design/testing-and-demos.md` § 5 and mirrored to the universal
`TESTING.md`:

The `evidence_ref` / `evidence_refs` drift survived because the contract
tests had been written by reading the code. The artifact whose job was to
catch the drift was derived from the thing it was checking. Its
replacement asserts the field name appears in the spec file.

Re-recording the statewide parcel fixture cleanly deleted five
cross-source exchanges that had accumulated across three sessions from
recording plans that no longer existed, breaking four tests in a
different directory with errors that pointed at the reader rather than
the writer. The recording plan now derives those cases from the registry.

**Adapter growth, and whether it is slowing.** Five declarative
additions this session — `numeric_fields`, `value_labels`,
`jurisdiction_scope`, `where_prefix`, `where_any_of`, `distinct_fields` —
each forced by a real layer. The new
`docs/audits/source-onboarding-cost.md` (closing #32) records what each
of eleven onboardings cost. Two needed no code, both today, and DEQ is
the stronger signal: a different agency, a different host, a MapServer
rather than a FeatureServer, and the adapter did not move. The earlier
changes were bugs where code assumed one source; today's move a fact
about a layer out of code and into the manifest, which is the direction
the metric is supposed to measure.

**Two dormant enum values started firing.** `alias_match` for a former
name, and `terms_note` for `Access.terms_gap` — DEQ's own www site
returns an Akamai 403 to a plain HTTP GET for its terms pages while its
GIS service answers anonymously, and none of its 97 open-data datasets
carries a license. A gap recorded only in YAML is a caveat one
contributor reads once; it is now a warning on every envelope citing the
source, retroactively covering Richmond's recorded gap too.

**Two spec decisions settled** (#21, #22) because the tool count finally
made them answerable. `default` is inside decision 0002's 8-12 band for
the first time, at nine, and both ceilings now refuse at expansion while
the floor warns and starts.

**Usability** (#30): four `examples/` scripts, each a real question with
a printed answer, running offline against recorded responses **by
default** rather than behind a flag — a newcomer's first run should not
be able to fail on a network. The offline seam moved out of
`tests/conftest.py` into the package so a script does not import a test
module, and each example is executed as a subprocess in CI exactly as a
reader would run it.

**Agents and tokens.** No delegated agents and no workflows this session,
deliberately: every step was either a live endpoint probe (curl, then a
`sources sample` recording) or an edit against a file already in context,
and both are cheaper done directly than described to a subagent. The one
place a fan-out would have paid is the four independent VGIN base-layer
registrations, which have identical shapes and no shared state — worth
trying next time a session registers three or more sources from one host.
The expensive habit this session did have was re-running the full suite
after every small edit; `pytest tests/servers/geo -q` first and the full
run at commit boundaries would have cost a fraction.

## 2026-08-29 — docs consolidation, a site rewritten for newcomers, six issues closed

Prompted by a review of the repo as a stranger would meet it. Two problems
with one cause: eight markdown files at the root, three over 80KB, with
the architecture in one and the reasons for it in another; and a site that
opened on a capability table full of undefined terms.

**Docs.** Root went from 8 markdown files to 2. `ARCHITECTURE.md` and
`DECISIONS.md` merged into `design/architecture.md`; `RESEARCH.md` became
`research/README.md`; `KNOWN_SOURCE_QUIRKS.md` became
`design/source-quirks.md`; the backlog and issue log became GitHub issues.
Four architecture sections were dropped as restatements of the decision
records they cited. Cross-references in 53 files updated.

**Site.** Opens on what the problem is, what MCP is, and what this project
does. Call cards and coverage blocks became accordions (47px collapsed,
down from ~400). The page had no responsive breakpoints at all before
this, only a dark-mode query, which is why the disclaimer and nav ran off
the side of a phone.

**Issues closed:** #15 (egress rules 6 and 7, plus a decompression limit
that did not exist), #18, #23, #24 (the license set decision 0011 chose,
absent from a public repo), #29 (`commonwealth configure`), #34 (ArcGIS
paging).

**Review.** Codex left 10 comments, a local pass found 11, one bug in
both. All 19 fixed. The one that mattered: the new paging walk extended a
list held inside a TTL-cached payload, so repeating a query returned 250,
450, 650, then 850 records. Two more in the same loop — sample mode was
paged past its own cap, and the duplicate-page guard could not do what its
comment claimed.

**Writing checker.** Eleven new rules, four ported from sibling checkers,
each with the sentence that prompted it as its test case. Four blind spots
closed, of which two were the checker's own bugs: its JS pattern skipped
every string containing an apostrophe, and its quote-pairing shifted every
pair after a short quote, hiding four banned phrases.

**Also.** Twenty cross-project references removed — the specs cited local
gitignored notes as an authority, which is both a dangling pointer and a
disclosure.

163 tests to 246.

## 2026-08-28 — plan-vs-built review: on track, 18 drift findings, docs corrected

An evaluation pass rather than a build session: the repo, demos, and
specs were checked against the adopted plan and the live ecosystem. Two
delegated agents ran — a code-vs-spec conformance audit, and a web
fact-check of the research claims the architecture rests on — and the
rest was verified directly. Suite at 163 passing; site verified
in-browser (14 recorded calls, resolver playground answering "Fairfax"
with two candidates, zero console errors).

Where the milestone stands: the first two stages of the adopted sequence
(../design/architecture.md § 39 — the contract spike and the geo vertical) are
substantially done. What milestone 1a still owes is exactly four things —
the incorporated town, the `parcel-zoning-screen` skill, Tier-2 evals,
and `configure` — so the GitHub issues was reprioritized to put those at the
top of High, and statewide-source breadth moved behind them.

The fact-check came back clean on everything structural: spec revision
2026-07-28 still current, `mcp==2.1.1` still latest, ETags and
progressive discovery still roadmap-only, the state/local civic gap
still unoccupied. Two commercial entrants (Regrid's parcel MCP, Esri's
Location Platform MCP beta) now sit in the parcels/geocoding lane;
../research/README.md part 3 § 9 records the pass. One finding removes a blocker:
VGIN's geocoder publishes no automated-use restriction at all, so
address resolution is no longer waiting on a terms question.

The conformance audit found 18 discrepancies; four were already fixed in
this session's working tree before it landed. The doc-fixable rest were
corrected in place with dated notes. Among them: the § 15 tool budget
still said 12–25 against 0002's chosen 8–12/20; three files cited a
"§ 17.6" the consolidation had silently dropped; several specs asserted
`configure`, capability-route generation, an `authoritative_only` flag,
resources, and `THIRD_PARTY_DATA.yml` in the present tense; the README
called 14 table rows "fourteen localities" when 12 are.

Four findings went to the GitHub issues as code work with an architect call
attached: the singular-`evidence_ref`-vs-plural-contract wire drift, the
untested egress rules 6–7, `discovery-min` amending 0001's letter
unrecorded, and two stale strings in code. One licensing gap got a High
backlog item: a public repo whose pitch includes "reuse this registry"
ships no LICENSE, NOTICE, or CC0 text — 0011 chose all of it, none is on
disk.

Worth it: yes. Nothing found argues with the architecture; what the
review found is ordinary spec-vs-code drift, caught while it is still
cheap to correct.

## 2026-08-28 — boundaries source, geo.find_boundaries, point-in-polygon

Registered VGIN's Administrative Boundaries FeatureServer (a new
`boundary.lookup` capability; two layers — 134 counties/independent cities,
191 towns) and built two things on it: `geo.find_boundaries`, the third of
four geo default tools, and point-in-polygon jurisdiction resolution, the
top High item in the GitHub issues. One source onboarding closed two milestones
because both questions are the same query against the same polygons.

Adapter work was the enabling piece: server-side geometry generalization
(`maxAllowableOffset`), platform centroids (`returnCentroid`), and metric
proximity buffering (`distance`/`units`) — each recorded in
`transformations` so a lossy step never rides silently. `find_boundaries`
returns bbox/centroid/area concise (~270 data tokens, well inside the
2000-token budget) and generalized rings only at `detail: "full"`, because
the resource store that should hold the true polygon does not exist yet.

Three findings the live data forced, none of them predictable from schemas:

1. **The design's centroid property test is false.** § 6 of
   design/jurisdiction-resolution.md proposed "every jurisdiction's
   centroid resolves to itself". Checked against all 134 real polygons, it
   fails for 4: Henrico, Henry, and Roanoke Counties each enclose an
   independent city, so they are topological donuts whose centre of mass
   lands in the city; York County needs no donut, its concavity around the
   York River is enough. The spec section is amended in place rather than
   quietly skipped, the evidence is committed
   (`docs/audits/centroid-property-2026-08-28.json`), and the shipped test
   asserts the corrected framing — a centroid is a label point, never an
   interior point, and nothing uses one for containment.
2. **Prince George County ships as two polygons** under one FIPS and GNIS
   (281 sq mi plus a 0.0076 sq mi sliver), which is why the layer holds 134
   rows for 133 localities. Both are returned with separate evidence; the
   county was added to the jurisdiction table specifically so the quirk is
   reachable through a tool and pinned by a test instead of being a note.
3. **A wrong call, caught by checking.** A buffered query at Fairfax City's
   centre returns Fairfax County at 40 m, which read as "the platform's
   distance parameter is unreliable — don't build on it". It is reliable:
   Fairfax County keeps a courthouse enclave *inside* the city, hence the
   city polygon's `ring_count: 2`. Verifying against the geometry instead
   of acting on the first reading is what saved the boundary-straddle
   warning, which is now a real check at a documented, explicitly
   project-chosen 50 m tolerance (VGIN publishes no accuracy figure and
   the code says so rather than inventing one).

All three are written up in the new `../design/source-quirks.md`, closing that
backlog item with observed variances rather than hypotheticals; each entry
names the test that holds it.

155 tests passing (up from 135), `doctor --live` green across all 6 sources
and 9 layers.

Later the same session, three things that were not the plan:

The README's status paragraph was 250 words in one block that never said
what a reader could do, reported internal bookkeeping to outsiders, and
claimed its own honesty. Rewritten around what works, what does not, and a
coverage table.

Then the doc tree: 45 prose files down to 25. Six research documents became
`../research/README.md`, fifteen decision records and the review round that revised
them became `../design/architecture.md Part 2`, and the design spec plus flow diagrams became
`../design/architecture.md`. The merge surfaced a real defect — every one of the
fourteen *chosen* decision records still said `Status: Open — architect to
choose` in its own header, correct only in the index table the records had
been separated from. The `design/` specs deliberately stayed separate
against the instruction to fold them in: source code cites them by filename
in 34 places and each is meant to be pulled into context alone. Three dated
filenames became sections with in-file changelogs, and `research/raw/` was
untracked (25 MB of regenerable API snapshots).

Last, the writing checker. It had passed that README paragraph while the
paragraph was the worst prose in the repo, which says what a phrase-only
lint is worth. It now reads paragraph structure rather than lines alone,
scans Python comments and docstrings for the first time, and bans two more
patterns taken from prose this repo actually shipped: claiming your own
honesty, and bureaucratic achievement-reporting.

Writing it produced its own lesson twice. The first version called `forced
the schema to be honest` self-praise, when that is the word doing real
work, and it reported its own rule table as slop. Both are pinned by tests
now, along with the original paragraph, in `tests/test_writing_lint.py`.
A checker with no test quietly stops catching things.

## 2026-08-28 — Charles City County, and civic's first real tool

Two more geo sources: Charles City County (a genuinely small rural
county — 6,514 parcels behind a deliberately minimal 2-field public
view, no zoning layer) closes the "rural county" half of design/
source-registry.md § 6's forcing set; a live search for Vienna's own GIS
(the "incorporated town" half) found only a zoning-map viewer app, no
queryable endpoint — likely genuinely thin, logged in the GitHub issues rather
than forced.

Bigger: `civic.get_code_section`, the first civic-vertical tool, and a
new adapter type. design/domain-servers.md § 5 explicitly defers domains
without registered sources ("writing tool lists before sources are
registered would freeze guesses") — civic was named as the sanctioned
next domain once the geo vertical's beta exit happened, which this
session's merged PR #1 satisfies. LIS's own JSON/XML API needs a
registration step this project can't do for itself (an actual API key);
the public law.lis.virginia.gov pages don't, so the tool reads those
directly — a new `virginia_law` adapter using stdlib `html.parser`
(no new dependency) rather than waiting on a credential. Named
`get_code_section`, not the design sketch's `search_law`: there's no
full-text search behind it, only direct citation lookup, and the sketch
name would overclaim.

Two real bugs found and fixed while building it, both via live
verification rather than the offline tests alone: the HTML parser
picked up an unrelated page-title `<h2>` before the real section
heading, concatenating "Code of Virginia" into every result (caught by
actually reading a live response, not just checking `found=True`); and
the site's coverage note produced a grammatically broken sentence
("also have their own local source" with no subject) for a capability
with zero local sources, since the code only handled "some local
sources" and "all local sources," not "none." Both are now regression
tests. `doctor --live` and `sources sample`'s single-adapter-type
assumptions (fixed for Richmond/VGIN earlier this session) got a third
occurrence here — extended again rather than special-cased, and doctor
now hard-fails on any *future* unrecognized adapter type instead of
silently skipping it. Full suite: 135 passed (up from 123 post-merge).

## 2026-08-28 — PR #1 review and merge: a real correctness bug caught pre-merge

Two rounds of Codex review on the bootstrap PR, both worth it. Round 1 (4
findings) was on the initial commit; a self-review (code-reviewer agent)
run first, independently, caught a fifth issue the bot didn't flag —
VGIN's statewide layer answering a locality-scoped PIN query with no
locality filter, so a jurisdiction with no local source could get back
*another* jurisdiction's parcel as a false hit (verified live: a Roanoke
County query returned a Henrico County parcel). Fixed with a fips-scoped
filter (`geo._scoped_where`), locked in with a regression test against a
real recorded exchange. Round 2, triggered by the round-1 fix commits,
found two more real bugs already latent in `find_zoning` from before this
session — the parcel-geometry lookup that determines a zoning answer was
never registered as a consulted source (a no-match reported zero
consulted sources for a call that actually happened), and a PIN plus only
`lon` or only `lat` silently fell through to the PIN path instead of
being rejected, unlike `find_parcel`. All 6 Codex findings plus the
self-review finding fixed, each with a regression test; final count 123
passed (up from 113 pre-review). [PR #1](https://github.com/pranava0x0/Commonwealth-MCP/pull/1)
merged, feature branch deleted, zero PRs left open.

## 2026-08-28 — first push, a logo bug, and a bootstrap-PR detour

The repo's first commit went to GitHub twice. The first attempt pushed
directly to `main` — a mistake against the user's own explicit prior
instruction to open a PR first for Codex bot review. Fixed by rebuilding
history so `main` carries a genuinely empty root commit that is a real
ancestor of the content commit (`git commit-tree` twice, chained by
`-p`), rather than two unrelated commits on differently-named branches —
`gh pr create` refuses branches with no shared history, and an orphan
commit doesn't satisfy that. [Pull request #1](https://github.com/pranava0x0/Commonwealth-MCP/pull/1)
now carries the real diff (175 files) for review before anything lands
on `main`.

Separately, the seal logo (wired in with a relative
`src="assets/seal.webp"`) broke when the page loaded through a
non-standard context (a `data:`-URL snapshot preview) — a broken-image
icon with the alt text overlapping the hero title. Fixed by embedding
both the logo and favicon as base64 data URIs, matching the page's
existing embedded-JSON pattern; the favicon specifically also moved from
WebP to PNG, since WebP favicon support is inconsistent across browsers
(Safari in particular) even though general `<img>` WebP support is fine.
Verified by opening the real `file://` path in-browser, not just the
served copy.

## 2026-08-28 — VGIN statewide parcels, real logo, demo/note drift fixes

Registered `va-vgin-statewide-parcels` (jurisdiction `va`), Virginia's
statewide parcels layer aggregated by VGIN from local submissions. Because
its jurisdiction is the state itself, it matches every jurisdiction's
resolved stack — ../design/architecture.md decision 0005 names this exact
pairing (a locality's own layer plus VGIN's statewide aggregation) as the
canonical example for "query both, never rank" (0005-C), and it now works
live: a Fairfax County parcel lookup queries both sources and returns
`comparison.agreement: true` on the same PIN (field-verified: Richmond and
Fairfax's own PIN format matches VGIN's `PTM_ID` field exactly). `parcel.
lookup` now covers all 13 seed jurisdictions; `zoning.lookup` still only
has Fairfax County and Richmond City, since VGIN publishes no zoning
layer — verified accurate live (Craig County: `find_parcel` hits, `find_
zoning` still returns `registry: none`).

Two more single-source assumptions broke on contact with a second/third
source and got fixed generically rather than patched around: `commonwealth
sources sample` assumed every arcgis manifest has a `zoning` layer
(VGIN doesn't), and the test suite's shared replay fixture pool
(`tests/conftest.py::build_ctx`, also used by `tools/build_site.py`'s demo
generator) only ever loaded Fairfax's recorded exchanges — both now
iterate the real registry generically. The site's "who has a real source"
note was rewritten from ad-hoc client-side jurisdiction math (which
produced "Virginia and Fairfax County and Richmond City have a source" —
wrong grammar and wrong: it was counting the statewide manifest's own
`jurisdiction: va` row as a "local" source) into a `capability_coverage`
block computed server-side by calling the real `SourceRegistry.select()`
per capability per jurisdiction — the same selection logic a live tool
call uses, not a browser-side reimplementation of it. That surfaced a
real, correct subtlety for free: Vienna (a town) shows as covered for
`zoning.lookup` because Fairfax County's manifest matches in Vienna's
resolved jurisdiction stack, without any special-casing.

Also landed the seal logo the user had been trying to get into the site
across most of the prior session (found saved to the project root as
`image-1787926135979.webp` — moved to `docs/assets/seal.webp`, wired in
as the nav mark, hero mark, and favicon; the hand-drawn placeholder SVG
symbol was removed). Full suite: 113 passed.

## 2026-08-28 — Richmond City: second registered source

Richmond publishes Parcels and ZoningDistricts as two separate ArcGIS
FeatureServers on the same host, not two layers of one service like
Fairfax — the existing adapter assumed a single `service_url` per
manifest. Added an optional per-layer `service_url` override to
`LayerDecl` (src/commonwealth/adapters/arcgis.py), tested with a
recording-fetcher unit test proving the override wins for the zoning
layer while parcels still falls back to the manifest default. Field
names and layer schemas verified live (`Parcels/FeatureServer/0`,
`ZoningDistricts/FeatureServer/0`); no Richmond-specific GIS disclaimer
page exists (checked rva.gov and the city's ArcGIS Hub site), so the
manifest's `terms_url` points at Esri's general terms with that gap
noted in `terms_notes` rather than inventing a page. Live health probe
(76,879 parcels, 679 zoning polygons) and both `geo.find_parcel` /
`geo.find_zoning` tool calls verified against real Richmond
data, including the parcel-geometry-intersects-zoning path that
exercises the cross-service_url split. Found and fixed a real bug along
the way: `commonwealth doctor --live` hardcoded the Fairfax manifest id,
so a second source silently went unprobed — generalized it to iterate
every registered ArcGIS manifest. Regenerated site data (sources: 1 → 2)
and rewrote the site's "only Fairfax has a source" note to derive its
count and jurisdiction names from the embedded registry data instead of
hand-typed prose, so it won't drift when a third source lands. Full
suite: 113 passed (was 112 before the new adapter test).

## 2026-08-27 — interactive demos + GitHub sync

One background research pass: compare docs/index.html against PNNL's
nepa-mcp, Power-Agent (confirmed Harvard SEAS-affiliated), civic-ai-tools,
github-mcp-server, fastmcp, and modelcontextprotocol.io — live pages
fetched, not guessed from repo names. Found civic-ai-tools is the only
checked project with a genuinely live in-browser demo; findings and what
was/wasn't adopted are in ../research/README.md part 6. Worth it:
yes — it caught that Power-Agent's tool→skill→benchmark layering (cited in
the reference evaluation) has no public visual demonstration anywhere,
which is why Commonwealth's site doesn't try to copy a pattern that doesn't
actually exist yet.

Built on that finding: three interactive demos added to docs/index.html,
all reading the same recorded 9-call run as the audit trail rather than a
separate simulation — a jurisdiction resolver playground whose answers are
precomputed by calling the real `JurisdictionTable.resolve()` at build time
(never a JS reimplementation that could drift; locked by a test comparing
committed output against a fresh build), the two ArcGIS-backed calls now
showing their actual outbound HTTP requests (via a `TrackingFetcher`
wrapper), and a coverage/warning-code decoder generated from the envelope's
own enums with a drift guard against `WarningCode`/`RegistryCoverage`/etc.
Full suite re-verified at 112 tests (109 prior + 3 new site-data tests),
browser-verified (DOM tree, live input interaction, click-to-scroll, zero
console errors, all three data files 200). Design revised against real
Virginia government sites (virginia.gov, fairfaxcounty.gov) rather than a
generic look, and the page's data was switched from fetched to embedded so
it renders correctly opened as a plain file, not only served over HTTP.
Repo initialized and synced to https://github.com/pranava0x0/Commonwealth-MCP.

## 2026-08-27 — contract spike implementation + audit-trail site

Single session, no delegated tasks. Shipped the contract-spike phase
per the adopted plan: package scaffold on the official MCP SDK v2
(compatibility spike passed — result recorded in ../design/architecture.md decision 0003), envelope +
coverage dimensions + evidence refs as Pydantic contracts with the committed
wire schema, exact jurisdiction resolution (13 seed rows, FIPS verified
against TIGERweb), egress policy with per-rule refusal fixtures, source
registry with activation gates and 0005-C top-two selection, ArcGIS adapter,
registry+geo tools, CLI (doctor/tools/sources/serve), recorded live Fairfax
fixtures via `sources sample`, and 109 offline tests including four
mutation-checked guards. Exit criterion met live: a real parcel's zoning
returned as a full envelope. Post-spike (user request mid-session): per-call
audit records derived from envelopes, wired into the server binding; a
deterministic 9-call demo generator (`tools/build_site.py`); and a static
GitHub-Pages-ready site (docs/index.html) rendering catalog + audit trail,
verified in the browser (DOM assertions + screenshots, zero console errors).
Four real bugs found and fixed during the build are logged in the GitHub issues.

## 2026-08-26 — research phase (design/spec session)

| Task | Why | Outcome | Worth it? |
|---|---|---|---|
| protocol-notes research | Verify current MCP spec/registry/SDK/client state (post-cutoff changes) against live docs; ≤25 fetches; wrote `research/notes/protocol-notes.md` incrementally | 324 lines, 26 fetches (1 over budget, justified in notes), 8 min. Caught the 2026-07-28 stateless spec redesign, SDK v2 rename, registry preview status, skills spec move — all post-cutoff facts the architecture would otherwise have missed. Headline claim independently re-verified before use. | Yes, decisively. |
| ecosystem-notes research | Survey exemplar MCP repos (changes to reviewed ones + new ones incl. Esri, Sentry, civic/federal servers) and their test/demo structures; ≤30 fetches; wrote `research/notes/ecosystem-notes.md` incrementally | 197 lines, 113 tool uses, 21 min. Routed GitHub reads through `gh api`/raw fetches so only 10/30 web budget spent. Found the github-mcp-server consolidation program, AWS successor-toolkit banner, live GSA catalog, civic-ai-tools, congressMCP test patterns, osmmcp's third design philosophy. One overclaim ("no official federal servers") corrected afterward — the Census Bureau's official server exists (`uscensusbureau/us-census-bureau-data-api-mcp`); synthesis carries the correction. | Yes. |

Script runs (not delegated research, logged for completeness): `search_hn.py` (234 stories, 30 threads), `search_github.py` (3 sweeps), `fetch_mcp_registry.py` (20K servers, hit page cap), `search_reddit.py` (blocked, exit 1 as designed). Community synthesis was done from script output plus 6 web searches directly.

## 2026-08-26 — review round 2 integration (external review feedback)

The user ran an external automated code review that produced
`../design/architecture.md Part 2 review round 2` and
`../research/README.md part 5`. Integration: verified the
review's sharpest factual claim (`ttlMs`/`cacheScope` scope) against the
previously-fetched changelog before applying; adopted the
coverage-dimension split, evidence references, wire-schema commitment,
declared/operational lifecycle split, data classification, capability
routing pre-Hub, `verification_mode`, external integration modes, the
geo-first re-sequenced plan, and three new decision records (0013-0015)
plus `design/security-and-data-handling.md`. Revised recommendations in
0002, 0005, 0008, 0010; recorded reviewer concurrence in the rest. Two
review items deliberately reshaped rather than copied: the egress "record"
is mostly fixed policy (0014 presents options only where real ones exist),
and 0008's revision keeps the Explorer spec as deferred design rather than
deleting it.
