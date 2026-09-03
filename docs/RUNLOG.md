# Run Log

One entry per significant work session or delegated research task: why it
ran, cost where relevant, and whether it was worth it.

## 2026-09-02 — the review of the above, applied

Fifteen findings from a review of PR #42, plus three from the Codex bot.
Five were bugs the tests did not reach; two were claims this branch made
that its own code contradicted.

**The fetch path.** Two of these predate the branch and were exposed by
rewriting `_fetch` around them.

A redirect dropped the query string. `params = {}` is not "no params" in
httpx — it *sets* the query, so a host redirecting
`.../query?where=...&f=json` to its canonical name was re-asked for a bare
`.../query`, answered with its HTML form, and was reported as an outage. A
test now drives a real 3xx through `_fetch`, which nothing did before.

Pinning the connection to a checked address had quietly given up
happy-eyeballs. `getaddrinfo` returns AAAA records with no IPv6 route and
usually sorts them first, and `approved[attempt % len(approved)]` gave
each address its own attempt — so a host publishing two AAAA before any A
would spend the whole retry budget on an address family the machine
cannot reach and report a healthy service as down. `services.arcgis.com`
resolves that way today, and it is the source that timed out in the first
audit run. Every approved address is now tried inside one attempt, so the
retry budget is spent on failures.

A proxy also stopped working the moment an explicit transport was passed,
because httpx reads `HTTPS_PROXY` only when there is none. Pinning and a
forward proxy genuinely cannot coexist, so the adapter says so once per
process rather than failing mutely.

**The result store.** One stray file in the shared cache stopped every
command from starting: `sweep()` caught three exception types and the two
it missed came from a JSON document that is not an object and a timestamp
in another format, and `load_context()` is on the startup path of the CLI
and the server alike. Reads had the same gap. Both swallow anything now,
and an unreadable payload reads as `not_found` rather than as a traceback.

An unwritable store failed calls whose inline answers were complete, and
the second geometry request killed `find_boundaries(detail="full")` for
every jurisdiction but the one whose un-generalized rings were recorded —
the offline replay seam raises a bare `AssertionError`, which
`except CommonwealthError` does not catch. Both degrade to "no handle this
time" now, which is what the docstrings already claimed.

Codex found the sharper one: `sensitive_public` sources were retainable.
`retention` defaults to allowed and the store only refused `restricted`,
while § 3 of the security spec has always required no stored payload
beyond the response cache for that classification. It is read off the
classification now — a rule that fires only when someone remembers a
second field is a reminder.

**The audit tool, one week old and already wrong in five places.**
Nullable columns reported drift from row order alone, and a real type
change was invisible while the first value stayed null; types are
collected across every feature now. `spatialReference` was captured but
never compared, so a projection change passed as unchanged. Renamed
geocoder fields did too.

The inventory skip tested for `"inventory"` while every such manifest
declares `none`, so four by-design non-probes were reported as missing
recordings. A failed probe wrote a null count into the reading history and
then crashed the report, committing the bad reading and losing the run. An
unreachable source was counted as changed, so a total outage read as
thirteen sources drifting. And `--out` raised after
writing the report, failing a job whose work had succeeded.

**Two claims this branch made about itself.** `containment.py` was the one
`selection_coverage()` call site left without a builder, and it is the
path a coordinate takes — so the registry-gap hint was not emitted
uniformly, whatever the run log said. And the entry above said the skill
capability check refuses to start while the spec and the code said it
warns; the behaviour changed partway through and the log did not follow.

**Also.** The site build wrote payloads into the developer's own cache and
baked a random handle into published data that no reader could resolve; it
uses a memory store with numbered ids now, so a rebuild produces the same
bytes. The README's claim that `tools/` is stdlib-only had been false
since `build_site.py` first imported the package.

565 tests.

## 2026-09-02 — drift on a schedule, floors from a range, and every question asked about one address

#31 and #19, and the Sterling walk that turned three latent problems up.

**#31: the fixtures get replayed against the live services.**
`tools/upstream_audit.py` sends every recorded request again and compares
what comes back structurally: field names and types, layer ids, geometry
presence, counts against the floors. A reordered feature list is not
drift; a retyped field is. It writes `docs/audits/upstream-<date>.md`,
which names every source under **changed**, **checked and unchanged**, or
**could not be reached**, because an empty diff and a source nobody
visited are different facts. Weekly, in
`.github/workflows/upstream-drift.yml`, which is under the fastest
`expected_cadence` any manifest declares.

The first run earned its keep immediately: Fairfax parcels 369,392 to
369,394, Richmond 76,879 to 76,908, DEQ stations 16,298 to 16,300, and one
VDOT read timeout that a re-run cleared. Ordinary churn, and nobody had
been able to see it before.

**#19: no floor rests on one reading now.** The readings that would have
answered this were already in the repository — every `sources sample` run
wrote the day's live feature count into the fixture summary, and it went
nowhere afterwards. `--backfill` collected them, so every probed layer has
its registration-day count and a live re-probe days later.

What the range says: every layer moved by under 0.05%. The floors sat 20%
under a single observation, which is far looser than the data needs, so
they were reset to ten per cent under the lowest reading, rounded down to
two significant figures, and never loosened. Fifteen layers, fourteen
tightened. Localities stayed at 130 against a count of 134, because a
percentage under a fixed set of governments would have been looser than
what was already there.

Two readings days apart cannot see an annual reassessment or a bulk
republish, so ten per cent is deliberately slack, and the audit keeps
adding readings.

**One address in Sterling, and what it exposed.** Sterling is a Census
Designated Place in Loudoun County — a postal city with no government —
and Loudoun registers no parcel or zoning layer here. Walking one address
there produces all three answers in a row: the parcel is **found** from a
statewide source, the zoning is **not covered**, and nearby public places
are **checked and absent**. `examples/one_address_every_question.py` runs
it offline, and the site's call trail now opens on it.

Recording that walk turned up three things worth having:

- `registry.resolve_jurisdiction` told a caller the table covered
  "counties and independent cities in the pilot set, and pilot towns".
  The table stopped being a pilot on 2026-08-29. A miss now says the
  table is complete, so an unmatched name is a neighbourhood, a postal
  city, or a CDP rather than a place not reached yet.
- `sample_pin` was whatever a parcels layer returned first, and Richmond's
  row order moved: a re-record renamed the PIN that fifteen tests,
  examples, and the site generator refer to by name. Each parcel manifest
  declares its sample PIN now, and #31 makes re-recording routine enough
  that this had to stop being luck.
- `test_point_query_path` took "the first point exchange in the file",
  which silently became a coordinate in another county once the recording
  gained a second point. It reads `sample_point` from the summary.

**CI exists.** `CONTRIBUTING.md` has been telling contributors that the
tests and the writing checker run on every pull request, and they ran
nowhere. `.github/workflows/ci.yml` runs both, with
`COMMONWEALTH_DENY_NETWORK=1` and a `git diff --exit-code` over
`tests/fixtures/`, so a run that reaches a government service or rewrites
a recording fails there rather than on someone's machine.

## 2026-09-02 — the result store, two more skills, and a doc consolidation

#26 settled, #33 built, the skill set to three, and `docs-practices.md`
folded away. Nothing pushed.

**#26: the warning is the answer.** § 3.7 used to say a point near a
shared boundary should return candidate jurisdictions the way an ambiguous
*name* does. It now records the opposite as the decision, with the
reasoning: the refusal would rest on a 50 m threshold this project
invented, VGIN publishes no positional accuracy for that layer, and one
number would be standing in for two unknowns — how far the point is from
the published line, which is measured exactly, and how far the published
line is from the legal one, which nobody knows.

An ambiguous name and a near-border point are not the same situation. A
name matching two governments has no answer to give. A coordinate falls in
exactly one polygon, and the doubt is about the map rather than the input;
returning candidates would misreport which. The reopen condition is a
measured figure for how far VGIN's lines sit from localities' own, which
#31's replay could collect as a by-product.

**#33: results have somewhere to live.** `core/results.py`, with 0013's
six properties: 128-bit ids, a 24-hour expiry stamped into the envelope, a
50 MB cap, write-time terms classification, an expiry sweep at process
start, and a disk directory behind the three methods an object store would
implement. `MemoryResultStore` shares the write and read paths rather than
reimplementing them, so the offline tests cannot describe refusals that do
not ship.

What it bought, in numbers: `geo.find_boundaries` at `detail='full'`
returns Fairfax County's boundary at 523 vertices inline and a handle to
the publisher's own 16,641. `geo.find_buildings` on downtown Richmond
returns 25 footprints inline and a handle to all 205, with the truncation
warning naming it. The handle lands in `_records_block()`, which seven geo
tools share, so it applies wherever a result truncates.

Handles resolve over the protocol as resource templates at the URIs the
envelope carries. Reading an expired one says so and names the call that
rebuilds it, and the error is raised as `ResourceError` because the SDK
re-raises that unchanged and wraps everything else in a generic message
that would have thrown that distinction away.

The un-generalized geometry needs a second request, so it was added to the
boundary source's recording plan and the fixture re-recorded: one query
added, 61 exchanges to 62, no existing response changed.

**Two more skills.** `whose-government` and `site-context-screen`, with
nine eval tasks between them, taking the set to three. Their walks replay
against fixtures alongside the first one's, and the format checks are
derived from what is on disk rather than named, so a fourth skill is
covered by them the day it is written. `tests/test_skills.py` is one file
now instead of one per skill.

The startup capability check became a warning. It refused to start when a
registry could not serve a skill's declared capability, which also refuses
a fork that registered one locality's parcels — punishing the wrong
person for the same reason decision 0002's amendment made the profile
floor a warning. Every tool still answers; only that skill's walk stops
early, and the log says which and why.

**Docs.** `design/docs-practices.md` is gone. Its § 1 described a
documentation tree that was never built and would now contradict `docs/`
being the published site; its tool-description template moved into
`domain-servers.md` § 1, which is where the code cites it from; the rest
went to CONTRIBUTING.md, where the people it addresses already look. That
takes `design/` from fifteen files to fourteen and leaves the root at two.

`design/README.md` opens with three files to read first and treats
`architecture.md` as a reference. It now has one ordered navigation path.

The full suite passed offline with the network denied.

## 2026-09-01 — the first skill, and four gaps between the docs and the code

Five issues: #39, #16, #41, #35, #27, plus one of #28's four
prerequisites. Nothing was pushed; the work sits on the branch for review.

**A test run stopped calling a live government service.** #39.
`sources sample va-vgin-composite-locator` ran as a subprocess in the
suite, and its docstring said "the run is expected to fail without a
network." On a connected machine it did not fail: it geocoded against
VGIN and rewrote the recorded fixture, so every contributor's `pytest`
left the working tree dirty and sent live traffic to a state geocoder.

The fix is a policy switch rather than a test patch.
`COMMONWEALTH_DENY_NETWORK` refuses every host in `EgressPolicy` before
the scheme, the allowlist, or DNS are looked at, through the same typed
`EgressRefused` as any other rule. The subprocess sets it and asserts the
fixture is byte-identical afterwards. Two egress tests that judge a URL on
its merits now clear the variable, so exporting it for a whole suite run
works — which is what turns "the tests are offline" from a habit into a
property. `COMMONWEALTH_DENY_NETWORK=1 pytest` passes.

**The DNS check now decides which machine is connected to.** #16. The
egress policy resolved a hostname and checked the addresses, and then
httpx resolved the same name again when it opened the connection. Whoever
controls a short-TTL DNS answer chose which of the two the connection
used. `validate_url` returns the addresses it approved and a
`PinnedAddressTransport` connects to one of them, carrying the hostname in
the `Host` header and in the TLS handshake so the certificate is still
checked against the name. The transport restores the hostname URL
afterwards, because `Response.url` reads through to the request and the
Code of Virginia publishes that URL as a section's `source_url`.

Two specs had described this as a re-check at connect time for weeks. Both
now say what the code does, with the date.

**Six status lines said the opposite of what shipped.** #41. The design
docs carry dated built-vs-planned annotations and the last two sessions
outran them: `geo.resolve_location` and address/ZIP resolution were
recorded as unbuilt, `configure` as not built, the license files as not
written, `parcel-zoning-screen` as shipped. Each is corrected in place
with its date rather than deleted. Five geo tools that shipped without a
contract entry — `find_address`, `find_buildings`,
`find_environmental_sites`, `find_landmarks`, `find_roads` — now have one,
written from the shipped signatures.

**The governance files exist.** #35. `GOVERNANCE.md`, `SECURITY.md`, and
`CODEOWNERS` under `.github/`, which keeps the repository root at README
and CONTRIBUTING while GitHub still surfaces the security policy and
honours the review routing. They are the last of the five prerequisites
`design/security-and-data-handling.md` § 5 sets before an outside source
manifest is accepted, and a repo-health test pins them. Private
vulnerability reporting is off in the repository settings and has to be
turned on for the channel `SECURITY.md` names to work.

**The first skill.** #27. `skills/parcel-zoning-screen/SKILL.md`, five
eval tasks, and a replay test that walks the skill's own sequence over
recorded fixtures for the four cases it promises to tell apart: one
polygon, the split parcel from #17, a locality with parcels and no zoning
source, and a locality with neither. Every expectation in the test is read
out of the task files, so a task and the code cannot drift apart.

Decision 0002 says profiles are generated from skill metadata. They still
are not, and the dated amendment says why: generating `default` from one
skill's two capabilities would delete the seven tools the 2026-08-29
amendment chose deliberately, and call that consistency. What is built
instead is the check — `check_skill_capabilities()` warns when no active
source answers a capability a skill requires, which is the
`design/hub-catalog.md` § 2 gate that had nothing to check until a skill
declared something. It warns rather than refusing for the reason 0002's
amendment gives about the profile floor: a fork registering one
locality's sources has a working server and one skill whose walk stops
early, and refusing to serve the tools that do work punishes the wrong
person.

Writing the skill turned up one thing worth recording: step 1 of every
walk, resolving the jurisdiction, is the one step with no capability id
behind it, because the jurisdiction table is not a registered source.

**One of #28's prerequisites.** `EnvelopeBuilder.next_action()` existed
and had zero call sites in `src/`, so no envelope had ever carried a
`next_actions` hint and the `registry_gap` trap would have passed against
an envelope that could not fail it. A total registry gap now carries the
hint, emitted from `selection_coverage()` so every tool that reports the
gap emits it the same way. It names `registry.search_sources`, a tool,
which is the one exception to the capabilities-not-tools rule and is
recorded as such: the registry's own tools read the registry rather than a
registered source. The site's Craig County demo call shows it.

`tools/check_writing.py` gained the `.github`, `skills/`, and `evals/`
trees, which `design/skills.md` § 4 had claimed for skills all along, and
one rule change: a comprehensive plan is the land-use document every
Virginia locality adopts under Code of Virginia § 15.2-2223, so the
llm-register rule steps around that one pairing and keeps banning the word
everywhere else.

**The reader-facing pages were the stalest files in the repo.** Asked
whether the doc structure works for someone new, and the structure is
fine: site to README to `examples/` is a good path and the site explains
MCP plainly. What failed is that the two pages written for strangers are
hand-typed prose that states numbers, while everything derived from the
registry updates itself.

`docs/llms.txt` said no geocoder was registered and street addresses did
not work, three days after both shipped, and put 12 localities in a
jurisdiction table holding 133. The site called `parcel-zoning-screen`
planned while it sat on disk, said "the four questions it can answer" over
a fourteen-tool server, and repeated the address claim.

And the town count: VGIN publishes 191 town polygons, two of which are
Census Designated Places with no government. Both were removed on
2026-08-30 with a test pinning their absence, and the README, the site's
own tooltip, and `jurisdiction-resolution.md` went on saying 191 — a
coverage claim, overstated, in the three places a stranger reads first.
All corrected to 189, and `test_site_data.py` now derives the number from
the table and fails on any other figure in those three files, including a
future one that is right today.

The site's skill roster reads `skills/*/SKILL.md` from disk now instead of
a typed list. `docs/README.md` says what that folder is, because `docs/`
holds the published site and not the documentation, and the name is the
GitHub Pages convention rather than a description.

461 tests, all passing, offline and with the network denied.

## 2026-08-29 — eleven sources, the full jurisdiction table, four drifts closed

Fifteen issues in one session: #2-#9 (sources), plus #14, #17, #21, #22,
#25, #30, #32. 247 tests to 364. `doctor --live` green across 17
manifests. [PR #38](https://github.com/pranava0x0/Commonwealth-MCP/pull/38).

**Sources.** Seven new registrations with a tool each — the VGIN
composite locator (`geo.resolve_location`), address points, building
footprints, landmarks, road centerlines, VDOT's LRS route master, and
DEQ's water-quality stations — plus four inventory-only manifests so the
registry's proposed/active split stops reading as zero coverage debt.

Four field checks changed a registration decision, and each finding
outlasts the source it came with:

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

**Two tests that passed on a wrong answer**, both written up in
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

Three findings from checking the live layers, none of them predictable
from schemas:

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
