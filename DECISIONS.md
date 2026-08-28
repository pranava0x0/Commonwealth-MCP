# Decisions

One record per architectural choice: the context, every credible option
written out with its evidence, a recommendation, and the choice actually
made. **Options are kept after a choice is made** — that is the point of
the format. A record you disagree with should be arguable from what is on
the page, not from memory.

Two of the fifteen were decided *against* the recommendation on file (0005
and 0015). Both say so, and both keep the rejected recommendation intact.

[RESEARCH.md](RESEARCH.md) is the evidence these were decided from.
`design/` holds the per-feature specs that implement them; each spec names
the decisions it depends on, and each decision names the specs it
constrains. To propose a new record, or to argue a chosen one should
reopen, see [CONTRIBUTING.md](CONTRIBUTING.md).

The blocking set for the contract-spike phase was 0001-0005, 0012, 0013,
0014, 0015 — all chosen.

| # | Decision | Status |
|---|---|---|
| [0001](#0001--v1-server-topology) | V1 Server Topology | Chosen 2026-08-26 |
| [0002](#0002--active-toolset-sizing-and-exposure) | Active Toolset Sizing and Exposure | Chosen 2026-08-26 |
| [0003](#0003--python-server-framework) | Python Server Framework | Chosen 2026-08-26 |
| [0004](#0004--ambiguity-interaction-pattern) | Ambiguity Interaction Pattern | Chosen 2026-08-26 |
| [0005](#0005--source-authority-rules) | Source Authority Rules | Chosen 2026-08-26 — architect override |
| [0006](#0006--data-retention) | Data Retention | Chosen 2026-08-26 |
| [0007](#0007--repository-layout) | Repository Layout | Chosen 2026-08-26 |
| [0008](#0008--explorer-execution-model) | Explorer Execution Model | Chosen 2026-08-26 |
| [0009](#0009--hosted-gateway--criteria-not-a-pick) | Hosted Gateway — Criteria, Not a Pick | Deferred to Phase 3 |
| [0010](#0010--entity-resolution--deterministic-only-or-probabilistic-too) | Entity Resolution — Deterministic Only, or Probabilistic Too | Chosen 2026-08-26 |
| [0011](#0011--license-strategy) | License Strategy | Chosen 2026-08-26 |
| [0012](#0012--canonical-schema-scope-for-v1) | Canonical Schema Scope for V1 | Chosen 2026-08-26, freezes at Gate A |
| [0013](#0013--result-handles-and-cache-backend) | Result Handles and Cache Backend | Chosen 2026-08-26 |
| [0014](#0014--egress-policy-and-data-classification) | Egress Policy and Data Classification | Chosen 2026-08-26 |
| [0015](#0015--developer-surfaces) | Developer Surfaces | Chosen 2026-08-26 — architect override |

---

## 0001 — V1 Server Topology

**Status:** Chosen 2026-08-26. One MCP server/process, domain code packages. Reviewer concurred.
**Context:** Design Spec § 5 settled the long-run shape (federated domain servers, Option C). This record is about V1 only: how many *processes* exist on day one, and what a "server" is to a first user. The 2026-07-28 stateless protocol (RESEARCH.md part 1 § 1) changes the calculus: with no sessions and no handshake, running several logical servers behind one process or one endpoint is mechanically simpler than it was.

---

### Option A: One process, three logical servers as toolsets

One `commonwealth serve` process exposing registry/geo/civic tools, partitioned by toolsets and tool-name prefixes. Domain boundaries exist in the code (separate packages, separate tool registries) but not in deployment.

- For: one install, one endpoint, one health check; cross-domain calls are in-process; the ten-minute-install criterion is easiest here; matches how GitHub's server handles a much larger surface (toolsets, not processes); toolsets already give task-size surfaces to clients.
- Against: fault isolation is nil (a geo dependency crash takes civic down); dependency graph unions (shapely/pyproj land in everyone's install); release cadence is coupled; the "federated" story exists only in code review, and drift toward a monolith is a standing temptation the promotion rule (§ 8) must actively resist.
- Evidence: community tool-count findings don't force process separation, only *surface* separation; heavyweight geo deps are real (pyproj wheels ~10-20MB, fine for one package). Statelessness removes the shared-session argument for co-location entirely.

### Option B: Three processes from day one (registry, geo, civic)

Independent `commonwealth-registry`, `commonwealth-geo`, `commonwealth-civic` processes; a client config lists three servers.

- For: honest federation from the start; per-domain dependency sets; fault and release isolation; matches the long-run production story so Phase 3 doesn't re-platform.
- Against: triple the install/config friction exactly when adoption is most fragile; three processes to health-check with no Hub yet; cross-domain joins (geo asking registry for source resolution) become network calls or shared-library calls anyway; V1's actual users (a handful) get zero benefit from the isolation.
- Evidence: GSA's catalog world assumes independent servers *with a gateway above them*; without the gateway, multi-server UX is the friction the community complains about (RESEARCH.md part 4 § 5-6).

### Option C: One process, but registry is a library, not a server

Geo and civic are the only tool surfaces; source resolution happens inside them via the registry as a shared library, with registry *tools* (search/describe sources) deferred until Explorer needs them.

- For: smallest possible tool surface for the core use cases; no "meta" tools competing for the model's attention against data tools (a real selection hazard: agents call registry.search_sources when they should call geo.find_zoning).
- Against: loses the discovery UX that makes the system explainable ("what sources does this cover?" is a question users ask on day one); Explorer and the contribution flywheel need registry tools soon anyway; hiding the registry makes coverage debt invisible to exactly the audience that could contribute.

### Recommendation

**A, with B's boundaries enforced in code**: one process for V1, three packages with no cross-imports except through Commonwealth Core, separate tool registries, toolset-per-domain, and the § 8 promotion rule applied at Phase 2/3 when hosting begins (geo is the likely first split: heaviest deps, spatial scaling). Registry tools ship but stay out of the `default` toolset (C's insight, kept): they live in a `discovery` toolset activated on demand.

**What would change this:** a Phase 1 contributor wanting to run only civic; a geo dependency conflict in practice; hosting earlier than planned. Any of those flips to B for the affected domain; the code boundaries make that a packaging change, not a rewrite. Bench toolset-size runs (design/bench.md § 5) showing meta-tool confusion would push registry tools further out of default profiles.

**Review round 2 (2026-08-26, external review):** concurs with A, with a framing correction adopted here: describe it as *one MCP server/process with three code packages*, not "three logical servers" — the client sees one server; the federation is an internal discipline until promotion actually happens. The narrowed plan (geo vertical first) makes this smaller still: V1 runs registry+geo packages, civic joins at the next milestone.

### Choice (2026-08-26)

**A, with B's boundaries enforced in code**, as recommended: one process, three packages (registry/geo/civic) with no cross-imports except through Commonwealth Core, separate tool registries, toolset-per-domain. Registry tools ship in a `discovery` toolset, not `default`. No change from the recommendation on file.

---

## 0002 — Active Toolset Sizing and Exposure

**Status:** Chosen 2026-08-26. 8-12 tool defaults, task ceiling 20 until local evals justify more.
**Context:** Design Spec § 15 budgeted 20-50 active tools. Field measurements since say that is the upper half of the danger zone: accuracy cliffs below 90% at 10-15 tools for small models and 20-30 for mid-tier ones; Anthropic's own guidance flags degradation past 30-50 and ships tool search with >85% context savings as the mitigation (RESEARCH.md part 4 § 1, RESEARCH.md part 1 § 4). The number is a product decision, not a footnote: it decides how many domains a "development due diligence" profile can span.

---

### Option A: Small fixed profiles (12-20 tools), more profiles

Default profiles stay under ~20 tools; cross-domain tasks get purpose-built profiles (development, procurement-scan) that cherry-pick 3-6 tools per domain rather than unioning domain defaults.

- For: inside the measured comfort zone for every model tier; profiles double as documentation of what a task needs; per-profile bench scores are meaningful.
- Against: profile proliferation is its own maintenance surface; a task that outgrows its profile mid-conversation hits a wall the user must notice ("switch to the spatial profile"); cherry-picking is a judgment that will sometimes be wrong.

### Option B: Design-spec status quo (20-50), rely on strong models

Keep generous defaults, accept that small models degrade, document "use a frontier model."

- For: fewer profiles to maintain; frontier models do hold 30-50 tools; simplest mental model.
- Against: contradicts the measured cliffs for everyone else; "works on Opus" is a bad pitch for a public-goods project whose university users run cheap models; the token dead-weight is paid even when accuracy holds.

### Option C: Lean on client-side tool search / deferred loading

Expose everything; mark all but a core set defer-loaded; let clients that support tool search pull what they need.

- For: aligns with where the protocol is going (server-side progressive discovery is on the roadmap); no profile curation; scales to the eventual 100+ tool ecosystem.
- Against: tool search support is uneven across clients today, and Commonwealth's audience skews toward hosted clients whose behavior we don't control; punts the curation problem to a ranking function nobody has tuned for civic queries; harder to bench ("which tools were even visible?" becomes a variable).

### Recommendation

**A now, C as it matures**: defaults of **8-12 tools per profile, task-profile ceiling of 20** until local Tier-2 evals justify more (tightened 2026-08-26 from 12-20/25 on review round 2 — the measured cliffs for small models sit at 10-15, and the burden of proof belongs on adding tools, not removing them). Cross-domain task profiles are curated by the skills (a skill's minimum data walk *is* the profile definition; generate profiles from skill metadata so the two never drift). Publish per-profile, per-model bench numbers (design/bench.md § 1 Tier 2) so the sizing argument stays empirical. Adopt deferred loading/progressive discovery the moment the client base supports it, using the same profiles as the ranking prior.

**What would change this:** local bench sweeps (the 15/28/50 task set) disagreeing with the published numbers; server-side progressive discovery shipping in the spec; a client-population survey showing tool-search support is already the norm among actual Commonwealth users.

### Choice (2026-08-26)

**A now, C as it matures**, as recommended: 8-12 tools per profile default, task-profile ceiling of 20. Profiles are generated from skill metadata so they never drift from what a workflow actually needs. Adopt deferred loading/progressive discovery once client support is verified, not assumed. No change from the recommendation on file.

---

## 0003 — Python Server Framework

**Status:** Chosen 2026-08-26. Official SDK v2 via a compatibility spike; exact-pin apps, ranged libraries.
**Context:** Design Spec § 26.1 said "FastMCP or official MCP Python SDK," which in mid-2026 names two different things: the official SDK v2 renamed its bundled high-level class from `FastMCP` to `MCPServer`, while the standalone `jlowin/fastmcp` project (now under PrefectHQ stewardship per the GitHub sweep) is at 3.4.7 stable with 4.0 in beta (RESEARCH.md part 1 § 6). Language itself is settled (Python 3.12+, design spec § 26.1; nothing in the research argues otherwise for a data-and-GIS project with this contributor pool), so this record is framework only.

---

### Option A: Official MCP Python SDK v2 (`mcp`, `MCPServer`)

- For: tracks the spec by construction (2.0.0 shipped the day of the 2026-07-28 revision); dual-era serving (2025-11-25 and 2026-07-28 clients simultaneously) built in; smallest dependency and concept surface; zero risk of framework-vs-spec version skew; the project's needs (typed tools, resources, structured output, Streamable HTTP) are all core SDK territory.
- Against: batteries not included — auth providers, middleware, server composition, and the niceties standalone FastMCP ships would be Commonwealth's to build (V1 needs almost none of them: no auth, no middleware beyond logging); fewer tutorials use the v2 idioms yet.

### Option B: Standalone FastMCP 3.x/4.x

- For: the ecosystem's most-used framework (self-reported: powering a large share of servers; top-40 by stars in our GitHub sweep); auth providers, middleware, composition/mounting, tool transformation, and a testing story out of the box; more contributor familiarity.
- Against: an extra abstraction layer whose release cadence is not the spec's — at research time it was unverified whether the released 3.x line fully speaks 2026-07-28 (stateless core, MRTR, `server/discover`), and 4.0 was mid-beta, which is exactly the wrong moment to adopt; the name collision with the official SDK's removed class guarantees documentation confusion; V1 uses none of the batteries that justify the layer.
- Note: FastMCP 1.0 was absorbed into the old official SDK; the projects have diverged since. "Community familiarity" partially transfers to the official `MCPServer` API, which is the same decorator lineage.
- Evidence for B worth weighing honestly: **PNNL's nepa-mcp — the closest domain analog, releasing weekly — builds on standalone FastMCP 3.4.4** (RESEARCH.md part 3 § 1.5), and its in-memory-transport pytest pattern plus `tool-fingerprinting` are FastMCP-documented features Commonwealth would otherwise hand-roll. The strongest peer chose B.

### Option C: Framework-agnostic core with a thin server shim

Commonwealth Core defines tools as plain typed functions + schemas; a small adapter binds them to whichever framework, so switching is contained.

- For: hedges the still-moving SDK landscape; keeps domain code framework-free (good for testing anyway).
- Against: an abstraction with one consumer on day one is exactly the speculative layer base-files/CLAUDE.md bans; both candidate frameworks are decorator-shaped, so the shim would mostly reinvent their surface; the real hedge is that tool logic already lives in core modules the servers import.

### Recommendation

**A: official SDK v2**, entered through a **compatibility spike** (the review's addition, adopted: prove the server path against real clients before committing the milestone to it — the SDK is a month old). Pinning nuance also adopted: applications and deployments lock the exact version; the published `commonwealth-mcp` *library* declares a controlled compatible range (`>=2.x,<3`), because a library that exact-pins its own dependencies breaks its consumers. Tool logic stays in framework-free core modules (C's discipline without C's shim — now formalized as DECISIONS.md 0015's shared core). Revisit at Phase 3 if hosting needs (auth middleware, composition) start reinventing standalone FastMCP; by then its 4.x line's spec support is a checkable fact instead of a beta bet. Write "official MCP Python SDK (`mcp` v2)" everywhere; never the bare word FastMCP.

**What would change this:** standalone FastMCP 4.x stable with verified 2026-07-28 support before Commonwealth's first server lands; an official-SDK regression pattern (v2 is one month old — watch its issue tracker during Phase 0); Phase 5 auth requirements arriving early.

### Choice (2026-08-26)

**A: official MCP Python SDK v2**, as recommended, entered through a compatibility spike before committing the milestone to it. Applications/deployments exact-pin the SDK version; the published `commonwealth-mcp` library declares a ranged compatible version (`>=2.x,<3`). Tool logic stays in framework-free core modules. No change from the recommendation on file.

**Spike result (2026-08-27):** passed, on `mcp==2.1.1`. Verified working: `MCPServer` + typed Pydantic returns → generated output schemas + `structured_content`; in-memory `Client(server)` testing; `result_type: complete`; dotted tool names; `ToolAnnotations(read_only_hint=...)`. Three traps found and handled, each with a regression test: (1) Python-side snake_case throughout (`output_schema`, not `outputSchema`); (2) `from __future__ import annotations` leaves tool hints as strings the SDK cannot resolve — bindings resolve signatures with `eval_str`; (3) the client validates `structured_content` against the output schema strictly, so the envelope schema must describe the exact wire shape, and typed errors must translate to the SDK's `ToolError` or the model sees a generic crash message. 0015's MCP-only note holds: since V1 uses none of standalone FastMCP's batteries, nothing observed argues for the extra layer.

---

## 0004 — Ambiguity Interaction Pattern

**Status:** Chosen 2026-08-26. Candidates-in-data hardened by bench; MRTR only after tested client support.
**Context:** Jurisdiction and entity ambiguity are constant in this domain (design/jurisdiction-resolution.md § 2.2), and agents demonstrably substitute world-knowledge guesses for literal inputs (RESEARCH.md part 4 § 8). The protocol offers two mechanisms to push a question back: return candidates in ordinary result data, or the 2026-07-28 MRTR pattern (`resultType: "input_required"`), which replaced server-initiated elicitation (RESEARCH.md part 1 § 1).

---

### Option A: Candidates in `data`, always

Ambiguous resolutions return `resolved: null` plus a `candidates` array with per-candidate evidence and distinguishers; the model relays the choice to the user.

- For: works on every client and protocol revision, including 2025-era ones; the interaction is visible in the transcript (auditable); bench can score it mechanically; no dependence on host UI affordances.
- Against: relies on the model to actually stop and ask instead of picking a candidate itself — the exact failure the pattern exists to prevent; costs a conversational round trip even when the host could have rendered a picker.

### Option B: MRTR input-required

Ambiguity returns `resultType: "input_required"` with a structured choice request; compliant hosts render a native picker and retry with the answer.

- For: protocol-blessed; the host UI enforces the stop (the model cannot silently pick); cleaner UX on supporting clients.
- Against: 2026-07-28-only, and host support is young and unevenly documented (no maintained core-feature matrix exists; RESEARCH.md part 1 § 7); non-supporting clients see a failed-looking interaction; harder to fixture-test across hosts we don't control.

### Option C: A, hardened by contract + bench (A with teeth)

Option A's shape, plus: tool descriptions state "never select a candidate yourself; present them"; the envelope carries a `requires_user_choice: true` flag hosts and skills can key on; bench ambiguity traps (design/bench.md § 2) gate releases on the surfacing behavior; skills' walk steps make the stop explicit.

- For: everything A gives, with the guess-risk addressed at the layers Commonwealth controls (descriptions, skills, evals) instead of the layer it doesn't (host UI).
- Against: a determined model can still guess; the mitigation is measurement, not enforcement.

### Recommendation

**C now; add B as progressive enhancement when host support is checkable.** The two compose cleanly: MRTR for hosts that advertise it (via `server/discover`-negotiated capabilities), candidates-in-data as the universal floor. The envelope flag ships either way so downstream code has one signal.

**Review round 2 (2026-08-26, external review):** concurs with C; sharpens the B trigger to *tested* client support (a client claiming MRTR in a matrix is not a client verified handling Commonwealth's input-required shape — test before enabling per client).

**What would change this:** host MRTR support becoming table stakes (watch the extension/client matrix); bench data showing models ignore candidates-in-data at unacceptable rates even with hardened descriptions — that result would justify B-only on supporting clients and a documented degradation elsewhere.

### Choice (2026-08-26)

**C now; add B (MRTR) later, per client, once tested.** Candidates-in-data — hardened by the "never self-select" tool-description contract, the `requires_user_choice: true` envelope flag, and bench ambiguity traps — ships as the universal floor for all clients from V1. MRTR is layered on top only for a specific client after its input-required handling is verified against Commonwealth's actual shape, not assumed from a capability matrix. No change from the recommendation on file.

---

## 0005 — Source Authority Rules

**Status:** Chosen 2026-08-26 — architect override. Query the top two, always surface agreement or conflict, no central ranking. Chosen against the B recommendation on file.
**Context:** The same fact often exists in two official places: a locality's own GIS layer and VGIN's statewide aggregation; an agency dashboard and its downloadable dataset; LIS's bill status page and the bulk data feed. Which is primary decides what agents cite. The registry schema carries `authority_level` per source (design/source-registry.md § 1); this record decides how those levels get assigned and what happens on conflict.

---

### Option A: Publisher-proximity rule

Authority follows proximity to the record's originator: the locality's own system outranks a statewide aggregation of it; an agency's system of record outranks its dashboard; bulk data and page views from the same publisher tie, resolved by freshness.

- For: matches how records actually flow (VGIN ingests locality parcel data on a lag; the locality is upstream); legally intuitive (the zoning administrator's county publishes the zoning); one rule covers most cases without a table of exceptions.
- Against: upstream is not always better in practice — some localities' endpoints are stale or broken while VGIN's aggregate is maintained; proximity says nothing about *quality*; requires knowing the actual flow direction, which is research per source pair.

### Option B: Per-capability authority table

A maintained table in the registry: for each (capability, jurisdiction-kind) pair, which source class is primary (parcels: locality-first; statewide road network: VDOT-first; addresses: VGIN composite first, because localities feed it on contract).

- For: encodes real knowledge instead of a heuristic; VGIN genuinely is the better first stop for some layers (its address program is the state's system of record in practice); reviewable, testable, citable.
- Against: a table to maintain and re-litigate; it would bake expert judgment about which source wins into central infrastructure — the same mistake design/adapters.md § 1 forbids inside adapters, moved up a layer (that cross-reference read "design-spec § 17.6" until the consolidation dropped the subsection; repointed 2026-08-28, argument unchanged); needs an owner.

### Option C: No central ranking; always query both, always surface both

Tools query the top two authorities and present agreement or conflict; no winner logic anywhere.

- For: maximally honest; conflicts are findings (a stale VGIN row IS information); zero rules to maintain.
- Against: doubles source load and latency on the common path where sources agree; pushes constant "both say X" noise into results; some capabilities have five plausible sources, and "both" doesn't generalize.

### Recommendation

**B, seeded small, with C's behavior on ties and conflicts — revised on review round 2 (2026-08-26) to name the modes honestly.** The original wording ("conflicts are always surfaced" while querying one source) hid a contradiction: an unknown conflict cannot be surfaced without a second query. Now explicit: tools accept `verification_mode: fast | corroborated` (default `fast`). `fast` queries the selected primary source; `corroborated` also consults an independent official source where one exists. *Known* conflicts (already recorded in the registry or discovered in-session) are surfaced in both modes; discovering *unknown* conflicts requires `corroborated`, which workflows opt into where the stakes justify the latency and source load (skills state which steps run corroborated). The capability vocabulary's `authority_order` block per capability stays as designed (ordered source classes, mandatory one-line reasons); disagreement between officials is always returned as a conflict, never reconciled (design spec § 28, unchanged). Option A survives as the default for capabilities the table doesn't cover yet: locality-first, with the fallback recorded in provenance.

**What would change this:** the first three localities' onboarding (design/source-registry.md § 6) will test the default against reality — if proximity keeps losing to statewide quality, flip the default; agency feedback (a Virginia agency stating its intended system of record) overrides research guesses and gets recorded in `authority_notes` with the communication cited.

### Choice (2026-08-26)

**C, not the recommendation on file:** no central ranking anywhere. Tools query the top two known-authoritative sources for a capability and always surface both — agreement or conflict — rather than picking a winner via a proximity rule or a maintained authority table. The architect's call, made explicitly against the B recommendation, prioritizing maximal honesty (a stale source is itself information) over the latency/source-load cost on the common path where sources agree. `authority_level` in the registry schema still records what's known about each source (for citation and for deciding *which* two sources are the top two to query), but nothing derives a single "primary" from it.

**Revisit if:** the doubled query cost/latency proves unacceptable in practice, or "top two" stops generalizing once a capability has many plausible sources — either would reopen this toward B.

---

## 0006 — Data Retention

**Status:** Chosen 2026-08-26. TTL cache plus result store, contingent on 0013; snapshots individually gated.
**Context:** Options range from "hold nothing beyond the request" to "snapshot government datasets over time." Retention interacts with source terms (some forbid redistribution/bulk storage), freshness honesty, storage cost, and a real product question: several high-value workflows (project chronologies, "what changed since") want history that sources don't keep.

---

### Option A: Transient only

No persistence beyond in-flight requests. Every answer is a live query.

- For: zero terms exposure, zero staleness ambiguity, zero storage ops; simplest trust story ("we hold nothing").
- Against: hammers government endpoints (rude and rate-limited); latency stacks on multi-source workflows; result resources (`commonwealth://results/{id}`) become impossible, which breaks the envelope's summarize-then-retrieve design; repeated identical queries in one session re-pay everything.

### Option B: TTL result cache + result-resource store

Response cache keyed by (source, query) honoring manifest `ttl_hint_seconds`; result resources persisted server-side for a bounded window (hours-days) so handles resolve; nothing else. Cache age always surfaced via the envelope's `cache_age_seconds`, and MCP `ttlMs`/`cacheScope` exposed to clients (RESEARCH.md part 1 § 1).

- For: matches the envelope design exactly; polite to sources; the protocol now has first-class fields for it; bounded windows keep terms exposure minimal (cached copies of things the source is currently serving anyway).
- Against: still no history; a result handle expiring mid-conversation needs a clean re-derivation story (handle carries the query, so re-run and note the re-retrieval).

### Option C: B + selective historical snapshots

B, plus scheduled snapshots for a reviewed list of sources where history is the value (planning-case lists, procurement postings — things that disappear when decided/awarded), stored as dated raw payloads with manifest-linked provenance.

- For: enables chronology and change-detection workflows nothing else can; government data genuinely vanishes (award postings especially), and researchers need the record.
- Against: this is where terms risk actually lives (retention and re-serving of a publisher's data); storage and pipeline ops; staleness presentation gets harder (serving a snapshot must never masquerade as current); Gate E exists precisely for this.

### Recommendation

**B for V1, C as a Gate E proposal per source, never a default — contingent on DECISIONS.md 0013** (review round 2: the result-resource half of B is unimplementable until the handle/backend design is chosen; choose 0013 first or together). The snapshot list, if approved, starts empty and each addition names: the workflow needing it, the terms reading permitting it, the staleness presentation, and the deletion story. Chronology skills in V1 build timelines from live queries of sources that DO keep history (LIS actions, meeting minutes) and simply report the gap where history doesn't exist — the gap is honest output, and it is also the Gate E evidence file.

**What would change this:** a partner institution (university library, state library) offering to be the archival home — archives are their job, and Commonwealth pointing at an institutional archive beats Commonwealth becoming one.

### Choice (2026-08-26)

**B for V1**, as recommended: TTL result cache + result-resource store (per DECISIONS.md 0013's backend), honoring manifest `ttl_hint_seconds`, cache age always surfaced via the envelope. **C only as a Gate E proposal per source, never a default** — each addition must name the workflow needing it, the terms reading permitting it, the staleness presentation, and the deletion story; the snapshot list starts empty. V1 chronology skills build timelines from live queries against sources that keep their own history, and honestly report the gap where a source doesn't. No change from the recommendation on file.

---

## 0007 — Repository Layout

**Status:** Chosen 2026-08-26. Monorepo with named split triggers. Reviewer concurred.
**Context:** Design Spec § 24 proposed monorepo `commonwealth-mcp` plus a later `commonwealth-mcp-catalog`, splitting Skills/Bench/Registry only when contributors justify it. The research adds texture: the exemplar projects that scale contributions (awslabs/mcp's many-servers monorepo; Power-Agent's three repos by concern; PNNL's per-domain servers sharing one repo) map cleanly onto the options.

---

### Option A: Single monorepo, everything

Servers, core, adapters, source manifests, skills, evals, catalog, docs in one repo (design-spec § 24.1 shape, catalog folded in rather than deferred).

- For: atomic changes across contract boundaries while they are still moving (envelope changes touch core+servers+fixtures together); one CI, one issue tracker, one place for the anti-slop and derivation gates; the catalog drift-test (design/hub-catalog.md § 1) is trivial in-repo; contributor onboarding is one clone.
- Against: source-manifest contributors (data people) clone a Python project; release versioning couples docs/data/code; repo size grows with fixtures.

### Option B: Design-spec § 24.1 as written — code repo + catalog repo

- For: the catalog's consumers (deployment tooling, gateways) differ from the code's; GSA's model.
- Against: the catalog is generated from server code (tool lists, capabilities); splitting the generated artifact from its generator invites the stale-mirror bug the base files warn about; two repos before Phase 3 hosting exists is speculative structure.

### Option C: Split source manifests out early (`commonwealth-sources`)

Code monorepo plus a data repo holding `sources/` and jurisdiction YAML, on the theory that data contributors outnumber code contributors eventually.

- For: lets localities/civic groups contribute without touching a Python tree; independent review cadence for data vs code; the registry-as-product story gets its own front door.
- Against: manifests validate against adapter schemas and canonical fields that live with the code — cross-repo contract testing before there are contributors is pure overhead; "eventually" is doing the arguing, and § 24.2 already names the split trigger.

### Recommendation

**A until a trigger fires, with § 24.2's triggers made explicit:** split `commonwealth-sources` when external (non-maintainer) manifest PRs are a steady plurality of activity; split the catalog when a Phase 3 gateway actually consumes it; split Skills/Bench when another state or org wants them without the Virginia data. Structure the monorepo so each split is a directory move: `sources/` and `catalog/` stay import-free (pure data + schema), skills depend only on capability IDs, bench depends only on published contracts.

**What would change this:** an institutional partner (a university civic-data lab) wanting ownership of the source registry ahead of schedule — governance can justify the split before volume does.

**Review round 2 (2026-08-26, external review):** concurs with A, including keeping the catalog in the monorepo until a real gateway consumes it.

### Choice (2026-08-26)

**A: single monorepo**, as recommended. Split triggers stand as written: `commonwealth-sources` splits out once external manifest PRs are a steady plurality of activity; the catalog splits once a Phase 3 gateway actually consumes it; Skills/Bench split once another state/org wants them without Virginia's data. `sources/` and `catalog/` stay import-free so each split remains a directory move. No change from the recommendation on file.

---

## 0008 — Explorer Execution Model

**Status:** Chosen 2026-08-26. No Explorer in V1 — the CLI covers exploration. A backlogged for Phase 4.
**Context:** design/explorer.md fixes Explorer's boundaries (registry-bound, read-only, enveloped). This record chooses what "query" means there. The community's token-economics case for code-mode is strong (150K→2K in Anthropic's example; Cloudflare's whole Code Mode design), and so is its security case against casual sandboxes (RESEARCH.md part 4 § 3-4).

---

### Option A: Declarative query objects only

`explorer.query` takes a typed filter/fields/geometry/pagination object; adapters translate. No code executes on Commonwealth infrastructure that a model wrote.

- For: the whole attack surface is a JSON schema; deterministic, fixture-testable, replayable; failures are explainable ("field X does not exist on layer 4"); adapters already need this translation layer for the semantic tools, so it is mostly free; nothing to sandbox, so nothing to mis-sandbox.
- Against: expressiveness ceiling — cross-source joins, aggregation beyond what a platform's query language offers, and multi-step exploration stay manual (the agent loops tool calls, paying tokens per hop, which is the cost code-mode exists to remove); some vendor query power (ArcGIS statistics, SoQL group-by) needs per-adapter surfacing to stay reachable.

### Option B: Sandboxed code execution against adapter clients

A constrained runtime (per-call sandbox: no network except adapter calls, no filesystem, CPU/memory/time limits) where the model writes code against typed adapter clients; only stdout/return value re-enters context.

- For: the measured token wins are real for chained work; long-tail exploration is genuinely faster when the model can loop/filter server-side; Cloudflare demonstrated the shape at production scale on isolates.
- Against: Commonwealth's V1 runtime is "pipx install on a laptop" — a laptop sandbox strong enough to trust is a project in itself (containers/jails per call), and a weak one is worse than none; the injection surface compounds (model-written code processing untrusted source payloads); auditability drops (reviewing generated code per call vs. a query object); the operational bar (limits, monitoring) is Anthropic's own stated trade-off.

### Option C: No Explorer in V1; CLI-based exploration for developers

Developers explore with `commonwealth sources probe/sample` and ordinary scripting; Explorer-as-MCP waits until demand is demonstrated.

- For: zero new surface; the promotion pipeline's real users in year one are contributors, who have the CLI; avoids building ahead of a user (base-files north star).
- Against: gives up the agent-assisted source-mapping flywheel (an agent drafting manifests from exploration is a genuinely good fit); "no long-tail story" weakens the coverage pitch; the registry-bound design makes A cheap enough that deferring saves little.

### Recommendation

**Revised on review round 2 (2026-08-26): C for V1.** The original recommendation (A thin in Phase 1) assumed a Phase 1 broad enough to have long-tail users; the narrowed geo-first plan removes them, and the contributor CLI (`sources probe/sample`, `tools call`) already covers exploration for the people actually doing it in year one — the review's point, and Option C's own argument, which now wins on the smaller V1. A (declarative `explorer.*` tools) becomes the Phase-4 entry point, with B (sandboxed code execution) revisited behind Gate B only on hosted infrastructure with isolate-grade sandboxing (Cloudflare's Dynamic Worker Loader is the reference bar). If B is ever adopted, its output still goes through the envelope, and generated code is logged verbatim for audit. design/explorer.md is marked deferred accordingly.

**What would change this:** hosted deployment arriving early with an isolate runtime in the stack; adapter experience showing the declarative object can't express what real exploration needs (log the refused-query shapes and let that corpus argue); protocol-level code-execution patterns standardizing (watch the working groups).

### Choice (2026-08-26)

**C for V1**, as recommended: no Explorer-as-MCP-feature; contributor CLI (`sources probe/sample`, `tools call`) covers exploration for year-one users.

**Backlogged, not dropped** — the architect explicitly wants A and B tracked as future work, not just implied by the trigger conditions above:
- **A (declarative `explorer.*` query tools)** — next in line, targeted for Phase 4 once V1's narrower geo-first scope broadens and long-tail users actually show up. Low risk to build when the time comes: registry-bound, typed, no code execution.
- **B (sandboxed code execution against adapter clients)** — the higher-value, higher-risk option for later; only revisit behind Gate B, and only once hosted infrastructure has isolate-grade sandboxing (Cloudflare's Dynamic Worker Loader is the reference bar). Do not attempt on the "pipx install on a laptop" V1 runtime.

---

## 0009 — Hosted Gateway — Criteria, Not a Pick

**Status:** Deferred to Phase 3. Open by design. The ten evaluation criteria are fixed now; the evaluation happens then.
**Context:** The gateway/aggregator field is crowded and churning (Obot/GSA pattern, Docker's toolkit+catalog, IBM ContextForge, commercial gateways; RESEARCH.md part 3). Choosing one in 2026-08 for a 2027 deployment would be picking a winner in someone else's race. What Commonwealth can fix now: what the winner must do, and what Commonwealth will refuse to depend on.

---

### Criteria (each scored when the evaluation runs)

1. **Protocol currency.** Serves 2026-07-28 stateless Streamable HTTP and whatever is current then; dual-era support for older clients; passes `server/discover` through honestly.
2. **Statelessness assumed.** No session-affinity requirements (Commonwealth servers won't provide sessions to pin). Plain reverse proxies stay on the candidate list precisely because the protocol no longer demands more.
3. **Toolset/profile awareness.** Can expose different tool subsets per endpoint/consumer, or gets out of the way while Commonwealth servers do it.
4. **Anonymous-first.** Public read-only access with no account must remain first-class; a gateway that forces auth onto free civic data fails outright.
5. **EMA-ready.** When authenticated tiers arrive (Gate D), Enterprise-Managed Authorization / ID-JAG is the institutional pattern (RESEARCH.md part 1 § 7); the gateway must support or not obstruct it.
6. **Health and observability passthrough.** Per-server health, OTel trace propagation, per-tool audit events — surfaced, not swallowed.
7. **Catalog ingestion.** Consumes Commonwealth's generated catalog (design/hub-catalog.md) or an export format the generator can emit; hand-maintaining a second catalog inside a gateway UI is disqualifying.
8. **Exit cost.** Config-portable (the catalog is the source of truth); no gateway-proprietary manifest becomes load-bearing.
9. **Operational weight.** Runnable by a small team on public-goods budget: memory footprint, upgrade cadence, failure modes. "A Kubernetes distribution" is a smell at this project's scale.
10. **License compatibility** with DECISIONS.md 0011's outcome.

### Standing candidates to re-check at Phase 3

Direct remote endpoints + reverse proxy (the null gateway — always the baseline to beat), GSA/Obot pattern (federal-adjacent credibility), Docker MCP toolkit/catalog, IBM ContextForge, whatever the ecosystem survey's successor finds then. The evaluation is a bounded spike scored against the ten criteria, written up as 0009's resolution.

**What would change this record:** a criterion proving wrong in practice (e.g., anonymous-first conflicting with abuse controls — rate limiting is the answer there, and the criterion should gain that nuance rather than fall).

---

## 0010 — Entity Resolution — Deterministic Only, or Probabilistic Too

**Status:** Chosen 2026-08-26. Normalized-name match is a candidate, never confirmed identity without a second key.
**Context:** Cross-source joins are a headline capability (project-trace, procurement scans), and the joins hang on identity: is "Example Development LLC" in Fairfax planning the same party as "EXAMPLE DEV LLC" in eVA? Design Spec § 29 mandates explicit match bases and visible ambiguity; this record decides how far matching may go beyond exact identifiers.

---

### Option A: Deterministic identifiers only

Matches only on exact keys: SCC entity ID, parcel ID, case number, bill ID, FEIN where public. Name similarity is never a match; it can be a *suggestion* labeled as such.

- For: every match is defensible and explainable ("same SCC ID"); no silent conflations of distinct LLCs (the base-files 2026-08-19 lesson about person-vs-company attribution is this failure class in the wild); simplest to test.
- Against: government data's dirty secret is that shared keys are rare across systems — eVA vendor IDs, SCC IDs, and locality applicant names rarely co-occur; A leaves the flagship join workflows mostly answering "cannot confirm same entity," which is honest and also nearly useless for the project-trace pitch.

### Option B: Deterministic core + declared normalization matches

A, plus a small set of *reviewable, deterministic* normalizations that count as matches when they produce exact equality: case/punctuation folding, legal-suffix normalization (LLC/L.L.C./Limited Liability Co.), whitespace, ampersand/and. Each normalized match carries `match_basis: ["normalized_name_exact"]` and the pre-normalization strings as evidence.

- For: captures the large fraction of real-world variance that is formatting, not identity; still rule-based, fixture-testable, no scores; the match basis says exactly what happened.
- Against: normalization rules accrete (is "The" stripping in? "Inc" vs "Incorporated"?); two genuinely different entities can normalize together ("Main Street Properties LLC" of two different counties), so jurisdiction/context guards are needed; the rule list is a mini authority table needing an owner.

### Option C: B + scored fuzzy suggestions, never auto-merged

B's matches, plus a suggestion tier (token-set similarity or similar) that only ever populates an `possible_matches` list with the evidence and an explicit "unconfirmed" label; skills may present suggestions to users, tools never join on them.

- For: surfaces the leads a human researcher would want without asserting them; keeps the flagship workflows useful; the confirmed/suggested split maps onto the envelope's ambiguity discipline.
- Against: scores are exactly the arbitrary-confidence numbers § 3.5 of the design spec bans from results — even labeled, they invite over-trust; threshold tuning is unowned work; suggestion quality varies wildly across name styles (trade names, DBAs).

### Recommendation

**B revised on review round 2 (2026-08-26): a normalized-name match alone creates a high-grade *candidate*, never a confirmed identity.** The reviewer's tightening is correct and this record's own Against section predicted it ("Main Street Properties LLC" of two different counties normalize together; applicant names are not registered entity names; DBAs exist). Confirmation requires normalized-name equality PLUS an independent corroborating key — same parcel, same address, same SCC/registered id — or explicit user confirmation; anything less ships in `possible_matches` with its evidence, not in `matches`. C's suggestion tier is accepted under the same score-free constraint (ordered by match-evidence kind, categorical, no floats). Normalization rules live in one reviewed module with fixtures per rule and a known-collision test set. Any move beyond that (embedding similarity, cross-field probabilistic linkage) is a new decision with Gate-A-level review.

**What would change this:** the first project-trace bench results — if B leaves the workflow hollow, C's categorical tier gets built; if C's suggestions mislead in evals, retreat and put the effort into acquiring real keys (SCC bulk data is the highest-value identifier source and its terms review should happen early regardless).

### Choice (2026-08-26)

**B, revised**, as recommended: normalized-name equality alone is a high-grade *candidate* in `possible_matches`, never a confirmed match in `matches`. Confirmation requires normalized-name equality plus an independent corroborating key (parcel, address, SCC/registered ID) or explicit user confirmation. C's fuzzy-suggestion tier is accepted under the score-free constraint — categorical, ordered by match-evidence kind, no floats. Normalization rules live in one reviewed module with fixtures per rule and a known-collision test set. No change from the recommendation on file.

---

## 0011 — License Strategy

**Status:** Chosen 2026-08-26. Apache-2.0 code, CC0 project data with third-party payload exclusions, CC-BY docs, DCO.
**Context:** Three licensable things with different logics: the code (servers, adapters, core), the data artifacts (source manifests, jurisdiction tables, capability vocabulary), and the docs/skills prose. Reference points: the surveyed ecosystem is overwhelmingly MIT/Apache-2.0 (github-mcp-server MIT, official SDKs MIT, awslabs Apache-2.0, PNNL's toolkit under a permissive lab license); government-adjacent data projects lean CC0/PDDL for data. The goal named in the project brief is maximum uptake by indie developers, researchers, and industry — an adoption goal, which argues against copyleft friction anywhere users integrate.

---

### Option A: MIT everywhere

- For: the ecosystem default; zero integration questions for companies; one license file; contributors know it.
- Against: MIT on *data* is awkward (attribution obligations on facts nobody owns); no patent grant (mostly theoretical here).

### Option B: Apache-2.0 code + CC0 data + CC-BY-4.0 docs

Apache-2.0 for code (explicit patent grant, contribution terms enterprises' counsel like); CC0 for manifests/jurisdiction data (facts about public systems should be maximally reusable, including by the government itself); CC-BY for the written docs and skills.

- For: each artifact gets the license its consumers expect; CC0 data invites exactly the reuse the registry exists for (a state agency copying manifests into an official catalog should face zero questions); Apache's contribution language substitutes for a CLA.
- Against: three licenses to explain; skills sit awkwardly between docs and code (a SKILL.md with scripts spans CC-BY and Apache — resolvable by licensing skill directories as Apache with the rest of code).

### Option C: AGPL code (+ open data)

- For: keeps hosted forks honest (a company running a closed, modified Commonwealth service must share).
- Against: kills the adoption goal for a real slice of industry users whose policies ban AGPL outright; contradicts the project's own dependency rule (the design spec § 35.9 already flags AGPL dependencies as a decision — shipping AGPL while avoiding AGPL deps would be incoherent); the "hosted fork" threat is small for a project whose moat is maintenance and authority, not code secrecy.

### Sub-decision: external code incorporation

Whatever the outcome: incorporating code from surveyed repos requires license-compatible provenance noted in the file header and NOTICE; unofficial-API client code is never vendored (terms risk travels with it); PNNL/Power-Agent patterns are re-implemented from their ideas, not copied, unless their licenses are confirmed compatible at the time.

### Sub-decision: third-party payloads and fixtures (added on review round 2, 2026-08-26)

CC0 applies to *project-authored* registry metadata only. Recorded fixtures and any retained raw payloads are third-party government content whose terms travel with them, and the review is right that a blanket CC0 would silently misstate their status. Adopted: a `THIRD_PARTY_DATA.yml` inventory, a NOTICE file, per-fixture source-and-rights metadata (written by `source sample` at recording time, from the manifest's terms fields), an explicit CC0 exclusion for third-party payloads in the license text, and DCO sign-off on contributions.

### Recommendation

**B, with the third-party exclusions above.** The split is worth its three-license overhead precisely because the data artifacts are the piece government and academia will reuse, and CC0 removes every excuse. Skills directories license as Apache-2.0 with the rest of the code tree; only `docs/` prose is CC-BY.

**What would change this:** a fiscal sponsor or university home with house rules; an agency partnership contingent on specific terms; evidence that dual-licensing confusion is actually deterring contributors (then collapse to A).

### Choice (2026-08-26)

**B**, as recommended: Apache-2.0 for code (skills directories included), CC0 for project-authored data artifacts (manifests, jurisdiction tables, capability vocabulary), CC-BY-4.0 for docs prose. Third-party payload exclusions and `THIRD_PARTY_DATA.yml`/NOTICE handling stand as specified above. DCO sign-off on contributions. No change from the recommendation on file.

---

## 0012 — Canonical Schema Scope for V1

**Status:** Chosen 2026-08-26, freezes at Gate A. Join-spine first; freeze on mapping evidence, never on a date.
**Context:** Design Spec § 9.1 lists seventeen candidate entities. Freezing all seventeen before mapping real sources would repeat Power-Agent's noted over-reach risk (a universal ontology nobody's data fits); freezing none leaves every tool inventing shapes. The base-files rule applies twice over: a spec's data assumptions are guesses until you query the data.

---

### Option A: Freeze the join spine only (5 entities)

`Jurisdiction`, `Source`, `Evidence`/provenance types, `Location`, `TemporalState`. Everything else (PlanningCase, Procurement, LegislativeItem...) ships as *documented tool result schemas* that may still change per release.

- For: the spine is what cross-source joins and the envelope actually require, and it is the part three localities of mapping evidence can validate quickly; domain shapes keep evolving with each new source without breaking the stability promise.
- Against: skills and downstream consumers get less contract than they'd like (a PlanningCase field rename is still churn for them, just churn without a broken promise); "stable spine, fluid domains" needs clear labeling or users assume more stability than offered.

### Option B: Spine + the V1 workflow entities (9-10)

A's five plus the entities the two V1 skills touch: `Parcel`, `PlanningCase`, `LegislativeItem`, `GovernmentAction`, and probably `Organization`.

- For: the V1 skills' output contracts get real foundations; these are exactly the entities Phase 1 sources force mappings for, so the evidence-before-freeze rule is satisfiable on schedule.
- Against: `GovernmentAction` is the riskiest schema in the whole design (every domain's events must fit it) and freezing it on two skills' evidence may bake in a civic/planning bias that procurement/environment data later strains.

### Option C: All seventeen, provisional-then-frozen

Publish all as "v0 provisional," freeze the lot at Gate A.

- For: one vocabulary from the start; contributors see the whole intended map.
- Against: fourteen of seventeen would freeze on zero or one mapped source each — the definition of guessing; provisional labels don't stop dependence (users build on what exists, labels notwithstanding).

### Recommendation

**A at Phase 0, graduating to B at Gate A** — with `GovernmentAction` explicitly held back until a second domain (procurement or environment) has mapped events into it, since it is the schema most likely to encode a first-domain bias. Every canonical entity page carries its mapping evidence (which real sources, which fields) the way the base files demand data-checked specs; an entity page without at least two source mappings cannot freeze.

**Review round 2 (2026-08-26, external review):** concurs with A, adding the sharpening adopted here: Gate A is triggered by *mapping evidence*, never by a calendar date — a freeze scheduled for a week number is a guess with a deadline.

**What would change this:** Phase 1 source work revealing the spine itself is wrong (e.g., `TemporalState` failing to represent LIS's action model) — that reopens A's list, which is the point of freezing late.

### Choice (2026-08-26)

**A at Phase 0, graduating to B at Gate A**, as recommended: freeze only the 5-entity join spine now. `GovernmentAction` is explicitly held back even at Gate A until a second domain (procurement or environment) has mapped real events into it. The freeze rule itself is adopted as policy, not a one-time call: no canonical entity page freezes with fewer than two mapped real sources, and Gate A triggers on mapping evidence, never a calendar date.

---

## 0013 — Result Handles and Cache Backend

**Status:** Chosen 2026-08-26. Stored resources for evidence and payloads, plus signed cursors for pagination.
**Context:** The envelope returns `commonwealth://results/{id}` handles for payloads too large for context (design/provenance-envelope.md), and the 2026-08-26 architecture review (DECISIONS.md review round 2 § 2.4) flagged the gap: the protocol is stateless and hosted replicas share nothing by default, so an in-memory handle minted by one replica is unresolvable on another. The handle design decides the cache backend, and DECISIONS.md 0006 (retention) is contingent on this record. Whatever is chosen must answer: identifier entropy, expiry, cross-replica access, authorization, maximum object size, re-query after expiry, deletion, and source-terms classification of the stored bytes.

---

### Option A: Server-side result store (shared object store when hosted)

Results persist under random IDs (128-bit, unguessable) in a store the resolution path reads: local disk for stdio/single-process V1, an object store (S3-compatible or similar) for hosted replicas. Handles carry only the ID; `resources/read` serves the stored envelope/payload with its `ttlMs`/`cacheScope` set from the source manifest.

- For: handles stay short; payloads of any size within a stated cap (suggest 50MB, GeoJSON gets big); deletion and expiry are store lifecycle rules; the stored object records its source terms classification so retention policy is enforceable per object; V1-to-hosted is a backend swap behind one interface.
- Against: hosted phase adds a stateful dependency to otherwise stateless servers; authorization becomes real the moment access classes exist (V1 public read-only makes every stored result public-class by construction, which must be asserted at write time, not assumed).

### Option B: Signed self-contained cursors (re-query, don't store)

The handle encodes the query itself (source, filters, page bounds) plus an HMAC; resolving a handle re-executes the query through the normal adapter cache. Nothing is stored beyond the ordinary TTL response cache.

- For: no result store to operate or authorize; replicas need only the signing key; nothing retained beyond the response cache, the smallest terms surface; expiry is just signature TTL.
- Against: resolution cost is a re-query (fine when the response cache is warm, a full upstream hit when not); a handle no longer denotes *the bytes the agent saw* — upstream drift between mint and resolve silently changes the payload, which is poison for an evidence system (the evidence ref must point at what was actually retrieved); large results re-page on every resolve.

### Option C: A for payloads, B's idea for pagination cursors only

Two mechanisms with distinct names: result *resources* (stored bytes, Option A) for evidence and large payloads; signed query *cursors* (Option B) for pagination continuation, where re-execution is the semantically correct behavior anyway.

- For: each mechanism does the thing it is honest at — evidence is frozen bytes, pagination is a live continuation; matches the protocol's own guidance that cross-call state is explicit server-minted handles.
- Against: two mechanisms to document and test instead of one.

### Recommendation

**C.** Evidence and oversized payloads are stored results (A): 128-bit IDs, default 24h expiry with the expiry stamped in the envelope, size cap stated and tested, write-time classification from the source manifest's terms/data-classification fields, deletion on expiry sweep. Pagination is signed cursors (B), TTL-bounded, carrying no payload. Expired handle resolution returns a typed error naming the re-query path (the handle's originating tool and arguments ride in the stored metadata / cursor, so "re-run this call" is a mechanical instruction). V1 single-process backend is a disk directory with the same interface the object store implements later.

**What would change this:** source terms forbidding even 24h retention for a load-bearing source (then that source's results go cursor-only and the envelope says payloads are re-derived); hosted-phase authorization requirements arriving before Gate D assumptions hold.

### Choice (2026-08-26)

**C**, as recommended: stored result resources (128-bit unguessable IDs, 24h default expiry stamped in the envelope, stated/tested size cap, write-time source-terms classification, expiry-sweep deletion) for evidence and oversized payloads; signed, TTL-bounded, payload-free cursors for pagination only. V1 backend is a disk directory implementing the same interface a hosted object store implements later. No change from the recommendation on file.

---

## 0014 — Egress Policy and Data Classification

**Status:** Chosen 2026-08-26. Fixed egress baseline; three-class classification with field allowlists; structural log minimization.
**Context:** A source manifest is an outbound network grant, and the 2026-08-26 review (DECISIONS.md review round 2 § 3.1-3.2) is right that "no arbitrary outbound" was asserted without an enforceable definition, and that `pii_risk` plus free-form notes under-specifies sensitive public data. The full policy text lives in design/security-and-data-handling.md; this record fixes the baseline and presents the genuine choices.

---

### 1. Egress baseline (proposed as non-negotiable, review then freeze)

Every outbound request from adapters, probes, or Explorer-class tools:

1. HTTPS required; plain HTTP only when a manifest declares `insecure_transport: true` with a written reason (some locality GIS servers are HTTP-only; the flag is visible in provenance warnings).
2. Destination host must match the manifest's registered host set; IP literals refused.
3. Resolved addresses in private, loopback, link-local, and cloud-metadata ranges are refused, and resolution is re-checked at connect time (DNS-rebinding defense).
4. Redirects followed only within the registered host set, max 3; credentials and auth headers stripped on any cross-host redirect.
5. Ports 443/80 only unless the manifest declares otherwise with a reason.
6. Response size and decompression-expansion limits enforced (defaults set in the spec; per-manifest overrides carry reasons).
7. Per-host concurrency caps and retry budgets from the manifest's politeness settings; probes never exceed their reviewed cadence.

These are testable: the security spec requires a fixture suite where each rule has a known-bad request that must be refused.

### 2. Choice: data classification granularity

Replaces `pii_risk`. Options:

- **A. Three source-level classes:** `open | sensitive_public | restricted`. `sensitive_public` requires a field-level exposure allowlist in the manifest (only listed fields leave the adapter), forbids raw-payload retention, and excludes values from logs. `restricted` cannot activate.
- **B. Field-level classification everywhere:** every mapped field carries a class; machinery is uniform but the common case (fully open GIS layers) pays schema weight for nothing.
- **C. Source-level class only, no field allowlists:** cheapest, but "this dataset is mostly fine except the owner-name column" — the actual shape of the problem in parcel and license data — is inexpressible.

**Recommendation: A.** The allowlist appears exactly where the risk does. A source with one sensitive column is `sensitive_public` with everything-but-that-column listed; a clean layer is `open` with no ceremony.

### 3. Choice: query-log and cache minimization for sensitive_public

- **A. Structural minimization:** logs for `sensitive_public` sources record tool, source, timing, and counts, never argument values or result fields; caches store responses under the same field allowlist (non-allowed fields dropped before the cache, not after).
- **B. Redaction at read time:** log/cache everything, redact on access. Rejected shape: retained-then-redacted is retained.

**Recommendation: A**, with one addition: the classification, allowlist, and reviewer + review date live in the manifest (design/source-registry.md), so the review trail is versioned with the grant it approves.

**What would change this record:** an agency partnership imposing its own handling standard (adopt theirs where stricter); Gate D authentication introducing per-user data (that re-opens § 3 with real PII stakes, and the threat model in the security spec must be revised first).

### Choice (2026-08-26)

All three parts adopted as recommended:

1. **Egress baseline** (§1) reviewed and frozen as written: HTTPS-required with reasoned exceptions, host-set matching with IP-literal refusal, private/loopback/link-local/cloud-metadata address refusal re-checked at connect time, bounded same-host redirects with credential stripping, restricted ports, response-size/decompression limits, and per-host concurrency/retry budgets — each with a fixture-tested known-bad request.
2. **Data classification** (§2): **A** — three source-level classes (`open | sensitive_public | restricted`), with `sensitive_public` requiring a field-level exposure allowlist in the manifest, no raw-payload retention, and exclusion from logs. `restricted` cannot activate in V1.
3. **Log/cache minimization** (§3): **A** — structural minimization for `sensitive_public` sources: logs record tool, source, timing, and counts only, never argument or result values; caches store only allowlisted fields, dropped before the cache rather than redacted after. Classification, allowlist, and reviewer/review-date live in the source manifest.

---

## 0015 — Developer Surfaces

**Status:** Chosen 2026-08-26 — architect override. MCP-only for V1. Chosen against the B recommendation on file; B backlogged as future expansion.
**Context:** The stated audience is indie developers, university researchers, and industry teams — many of whom build scripts, notebooks, and ordinary web services, not agents. The 2026-08-26 review (§ 4.4) and the tools research (RESEARCH.md part 5 § 8) surfaced a production public-data precedent: NCI's Imaging Data Commons runs one backend-agnostic core exposed through thin REST and MCP adapters, with documented guidance on when callers should use which. The question: is Commonwealth an MCP project, or a capability core with MCP as one caller surface?

---

### Option A: MCP-only (plus the CLI as a debug tool)

- For: one surface to contract-test, document, and secure; the CLI already exists for scripting; smallest V1.
- Against: a researcher writing a notebook against zoning data should not need an MCP client loop; "install an agent to query public data" filters out a large slice of the stated audience; the CLI-as-API pattern (parsing `--json` output) is a worse Python library with extra steps.

### Option B: Shared core, three surfaces now (Python library, CLI, MCP), REST later

Capability logic lives in framework-free core modules (typed functions + schemas, no MCP/CLI imports). The Python library IS the core's public API; the CLI and MCP server are thin bindings over it; a REST/OpenAPI adapter arrives with the hosted phase.

- For: implements each capability once (the review's requirement); the notebook user gets `pip install commonwealth-mcp` and calls `geo.find_zoning(...)` directly, envelope and all; the MCP and CLI layers stay honest because anything they can do the library can do; IDC demonstrates the shape working for exactly this audience mix; DECISIONS.md 0003 already pushed tool logic into framework-free core, so this is that discipline given a name and a public door.
- Against: the library API becomes a versioned public contract earlier than planned (semver discipline from the first release); docs must serve two calling styles; envelope ergonomics in plain Python need care (typed result objects, not raw dicts).

### Option C: REST-first

Stand up a hosted REST API as the primary surface, MCP as a wrapper.

- For: the most universally consumable surface.
- Against: requires hosting from day one, which the V1 plan deliberately avoids; agents are the wedge audience and the differentiated surface; this is Option B's Phase-3 tail promoted to the head for no V1 user.

### Recommendation

**B.** Concretely: `commonwealth.core` (or equivalent) is import-clean of MCP/CLI dependencies and contract-tested on its own; the library's public functions return typed envelope objects; CLI and MCP bind to it; REST/OpenAPI is committed for the hosted phase and its future existence shapes nothing now except the no-framework-imports rule. Success metric already on file: an outside developer completes a query from a notebook without touching MCP.

**What would change this:** V1 usage showing the library surface unused (then it demotes to internal API without breaking anything — that reversibility is part of why B is safe); a hosted partner wanting REST early (pulls C's tail forward, still on the same core).

### Choice (2026-08-26)

**A, not the recommendation on file:** MCP-only for V1, with the CLI as a debug/scripting tool, not a supported public API. Matches the norm among surveyed civic-data peers (Census Bureau, GovInfo, and Data Commons' official MCP servers are all MCP-only; PNNL's `nepa-mcp` ships an MCP server plus a debug CLI, not a parallel library). Tool logic still lives in framework-free core modules per DECISIONS.md 0003 — that discipline is retained regardless — but the core is not committed as a versioned, documented, semver-disciplined public Python library at this time.

**Backlogged, not dropped** — the architect explicitly wants B tracked as future expansion:
- **B (shared core exposed as a first-class Python library, + REST later)** — the Imaging Data Commons precedent (RESEARCH.md part 5 § 8) is the reference shape if this gets built: `commonwealth.core` import-clean of MCP/CLI dependencies, public functions returning typed envelope objects, CLI and MCP as thin bindings over it, REST/OpenAPI arriving with the hosted phase. Because core logic is already framework-free (0003), promoting it to a public library later is additive — no rewrite required, only documentation, semver commitments, and packaging.
- **Trigger to revisit:** evidence of real non-agent demand (a researcher/notebook user asking for direct library access instead of going through MCP or scraping CLI output), or a hosted partner wanting REST early.
---

## Review round 2 (2026-08-26)

An external automated review of the architecture and plan. Its adopted corrections are already folded into the records above and into the specs in `design/`; this is the round itself, kept because knowing what was challenged is part of knowing why the answers stand.

<sub>Was `docs/architecture-plan-review-2026-08-26.md` — “Commonwealth-MCP Architecture Plan Review”.</sub>

**Date:** 2026-08-26  
**Status:** Review memo. No recommendation here is an accepted project decision.  
**Audience:** Human architect and the next coding agent.  
**Companion research:** [Relevant MCP Tools and Integration Opportunities](../research/relevant-mcp-tools-2026-08-26.md)

### 1. Verdict

Keep the architecture. Change the delivery plan.

Strong parts:

- The Government Source Registry is treated as a durable product.
- Semantic tools hide vendor APIs without hiding source evidence.
- Provenance, jurisdiction, coverage, and evaluation are first-class contracts.
- Read-only operation is the V1 default.
- Adapters, core semantics, MCP servers, and skills have clear responsibilities.
- Open decisions are recorded instead of buried in implementation.

Main weakness: V1 is too large. The current plan attempts two domains, three adapters, many sources, two skills, a CLI, health monitoring, schema work, evaluations, and public documentation. That can produce many partial systems without one convincing developer experience.

The first release should prove one complete path:

```text
source manifest
  -> validated adapter
  -> semantic capability
  -> evidence envelope
  -> MCP and CLI surfaces
  -> one evaluated workflow
```

### 2. Blocking contract changes

#### 2.1 Split coverage into independent dimensions

The current `complete | partial | no_coverage | failed` status combines four different questions:

1. Did the queries finish?
2. Does the registry cover the requested place and capability?
3. Did pagination finish?
4. Did the upstream publisher expose a complete record set?

Use separate fields:

```yaml
coverage:
  registry: covered | partial | none | unknown
  execution: complete | partial | failed
  pagination: complete | truncated | unknown
  source_claim: complete | partial | unknown
  result: hit | empty
```

An empty result is a successful result state, not an exception. Remove `NoResults` and `PartialResults` from the error taxonomy. Keep failures for conditions that prevent a valid answer.

#### 2.2 Make claim-to-evidence links explicit

Per-source provenance cannot prove which source supports each record in a mixed chronology. Every material record and finding should carry references:

```json
{
  "finding_id": "finding_01",
  "evidence_refs": ["evidence_01"],
  "source_refs": ["source_01"]
}
```

Each evidence object should record:

- registered source ID,
- publisher record ID,
- stable locator when one exists,
- retrieval and source-update times,
- transformation chain,
- payload hash when raw retention is allowed,
- raw-recovery state and reason when it is not.

This makes the skill-level evidence matrix mechanically testable.

#### 2.3 Define the exact MCP wire shape

Publish one JSON Schema that shows where these values live:

- MCP `resultType`,
- `structuredContent`,
- Commonwealth envelope,
- `_execution`,
- `isError`,
- resource links,
- protocol `_meta`.

Do not leave transport placement to each tool author.

The 2026-07-28 MCP `ttlMs` and `cacheScope` fields apply to list/read results such as `tools/list` and `resources/read`, not ordinary `tools/call` results. Source freshness therefore remains part of the Commonwealth tool envelope. Protocol cache hints can describe result resources and catalogs. They cannot replace tool-result freshness fields.

#### 2.4 Decide how result handles work

Stateless hosted replicas cannot resolve an in-memory result handle created by another replica. Add a decision covering:

- shared object store versus signed self-contained cursor,
- identifier entropy,
- expiry,
- cross-replica access,
- authorization,
- maximum object size,
- re-query after expiry,
- deletion,
- source terms and data classification.

Suggested record: `0013-result-handles-and-cache-backend.md`.

#### 2.5 Separate declared lifecycle from live health

Do not use one field for both reviewed source state and temporary outages.

```yaml
declared_state: proposed | active | retired
operational_state: healthy | impaired | unavailable | unknown
```

`declared_state` belongs in version control. `operational_state` belongs in runtime monitoring storage. Scheduled probes should not open routine outage PRs.

### 3. Security and governance gaps

#### 3.1 Outbound network policy

A source manifest is an outbound network grant. Define:

- HTTPS required by default,
- private, loopback, link-local, and metadata addresses blocked,
- DNS rechecked when connecting,
- redirects limited to registered hosts,
- permitted ports,
- response and decompression limits,
- per-host concurrency and retry budgets,
- credentials removed on cross-host redirects.

Add a project-root threat model. The current `base-files/SECURITY.md` is a house template, not a Commonwealth-specific security contract.

Suggested record: `0014-egress-and-data-classification.md`.

#### 3.2 Sensitive public data

Public access does not make every field safe to aggregate, cache, log, or republish. Add:

- field-level exposure allowlists,
- a `sensitive_public_data` classification,
- query-log minimization,
- cache classification,
- raw-payload retention rules,
- redaction and display policy,
- a review owner and review date.

`pii_risk: present` plus free-form notes is insufficient.

#### 3.3 Source licensing and fixtures

Apache-2.0 code, CC0 project-authored registry metadata, and CC-BY documentation remain sensible. Raw government responses and recorded fixtures may have different terms.

Add:

- `THIRD_PARTY_DATA.yml`,
- a NOTICE file,
- per-fixture source and rights metadata,
- an explicit exclusion of third-party payloads from blanket CC0,
- a Developer Certificate of Origin for contributions.

#### 3.4 Stewardship

The registry needs named responsibilities:

- capability vocabulary maintainers,
- source reviewers,
- terms and sensitive-data reviewers,
- release maintainers,
- security response owner,
- deprecation policy,
- source abandonment and transfer process.

Add `GOVERNANCE.md`, `CONTRIBUTING.md`, project `SECURITY.md`, and CODEOWNERS before accepting external source manifests.

### 4. Routing and federation gaps

#### 4.1 Capability routing must exist before the Hub

V1 skills name capability IDs, but the current plan assigns capability routing to the Phase-3 Hub. Add a local routing mechanism now:

```text
commonwealth serve --profile development
commonwealth configure <client> --profile development
```

Generate capability-to-tool bindings from one registry. Skill metadata should list required capability IDs. Startup should fail when a required capability has no route or has an unresolved duplicate.

#### 4.2 Authority verification modes

The plan says conflicts are always surfaced but normally queries only the first healthy source. Unknown conflicts cannot be surfaced without a second query.

Use:

```text
verification_mode=fast
verification_mode=corroborated
```

`fast` uses the selected primary source. `corroborated` consults an independent official source where one exists. State that known conflicts are always surfaced. Require corroboration only for workflows that justify its latency and source load.

#### 4.3 External MCP output is not automatically Commonwealth output

A catalog entry does not make an external server conform to Commonwealth capability IDs, coverage semantics, or provenance envelopes. Support two explicit modes:

1. Native external MCP: the skill understands its foreign contract.
2. Commonwealth wrapper: a maintained translation maps foreign output into the envelope.

Never imply uniform federation based only on catalog registration.

#### 4.4 Expose the core beyond MCP

The audience includes indie developers, universities, and industry teams. Many will build scripts, notebooks, websites, or ordinary services rather than agents.

Keep capability logic in a framework-free core. Expose it through:

- Python library,
- CLI,
- MCP,
- later REST/OpenAPI when hosting begins.

Do not implement the same capability four times. Add a decision for MCP-only versus shared core with multiple thin surfaces. The companion research documents a production public-data example using one core for REST and MCP.

Suggested record: `0015-developer-surfaces.md`.

### 5. Recommended disposition of existing decisions

| Decision | Recommendation |
|---|---|
| 0001 topology | Choose A. Describe it as one MCP server/process with three code packages, not three logical servers. |
| 0002 toolsets | Choose A. Default 8-12 tools; task-profile ceiling 20 until local evaluations justify more. |
| 0003 framework | Choose official Python SDK v2 after a two-day compatibility spike. Exact lock for applications; controlled compatible range for the published library. |
| 0004 ambiguity | Choose C. Add MRTR only after tested client support. |
| 0005 authority | Choose revised B with `fast` and `corroborated` modes. |
| 0006 retention | Choose B only after the result-handle decision. |
| 0007 repository | Choose A. Keep the catalog in the monorepo until a real gateway consumes it. |
| 0008 Explorer | Choose C for V1. The contributor CLI already provides exploration. |
| 0009 gateway | Keep deferred. |
| 0010 identity | Revise B. A normalized name alone creates a candidate, not a confirmed identity. |
| 0011 license | Choose B with third-party fixture and payload exclusions. |
| 0012 schema | Choose A for V1. Freeze only after mapping evidence, not on a calendar date. |

### 6. Revised plan

#### Phase 1: contract spike

- Choose blocking decisions.
- Prove the official SDK server path.
- Register one ArcGIS source.
- Define envelope wire schema and coverage dimensions.
- Implement exact jurisdiction lookup.
- Define outbound-network policy.
- Add Tier-1 contract tests.

Exit: one address or parcel query returns valid evidence and honest coverage.

#### Phase 2: geo vertical

- Build registry and geo packages in one process.
- Ship `geo.find_parcel` and `geo.find_zoning`.
- Cover Fairfax County, Richmond City, one rural county, and one nested town.
- Record real fixtures.
- Ship `doctor`, direct tool calls, source validation, and profile activation.

Exit: another ArcGIS locality can be added through a manifest without server-code changes.

#### Phase 3: developer product

- Publish source-authoring and capability-extension contracts.
- Add dry-run and idempotent client configuration.
- Complete source terms and sensitive-data review flow.
- Add Tier-2 tool-selection evaluations.
- Ship one narrow skill such as `parcel-zoning-screen`.

Do not call the first workflow `development-site-due-diligence` until environmental, infrastructure, planning-case, and meeting coverage justify that name.

Exit: an outside developer can add a source and build a working tool without maintainer help.

#### Phase 4: hardening and beta

- Implement result-resource storage.
- Add runtime health overlay.
- Add injection and source-failure fixtures.
- Enforce privacy and logging rules.
- Test four representative MCP clients.
- Publish benchmark baseline, limits, and source coverage.
- Release public beta.

Start the civic/LIS vertical after this exit. Defer Hub, Explorer, finance, infrastructure, environment, authenticated sources, and writes.

### 7. Success metrics

Add these to the existing V1 acceptance criteria:

- median time to add an ArcGIS source,
- percentage of source additions needing no server-code change,
- coverage-state accuracy on hidden traps,
- claim-to-evidence completeness,
- tool-selection accuracy by model and profile,
- warm healthy-source latency,
- partial-response deadline during an upstream outage,
- install success by supported OS and Python version,
- number of outside developers completing the quickstart without maintainer help.

Initial performance budgets should be hypotheses, measured during the spike, then frozen:

- `data` target no more than 2,000 tokens,
- one retry within the total request deadline,
- bounded concurrency per government host,
- stale-if-error only when the envelope says it is stale,
- no upstream health probe more often than its reviewed politeness budget.

### 8. Instructions for the next coding agent

1. Read the companion MCP-tool research.
2. Do not write implementation code while required decisions remain open.
3. Turn the five suggested records into complete decision records.
4. Reconcile the existing design spec with the coverage and cache-hint corrections.
5. Present contract diffs to the human architect before changing schemas.
6. Keep Explorer and hosted-gateway work out of the first implementation milestone.

---

## Changelog

| Date | What changed |
|---|---|
| 2026-08-26 | All fifteen records drafted with options and recommendations. |
| 2026-08-26 | Fourteen chosen in one architect pass; 0009 deferred to Phase 3 by design. 0005 and 0015 decided against their own recommendations, both recorded in place. |
| 2026-08-26 | Review round 2 revised the recommendations in 0002, 0005, 0008 and 0010, and added 0013-0015. See [the review round](#review-round-2-2026-08-26) below. |
| 2026-08-28 | Fifteen files merged into this one. **Every chosen record's own Status line still read "Open — architect to choose"**, correct only in the index table it was separated from; an agent reading a record directly would have been told the choice was still open. Statuses are now stated with each record. No option, recommendation, or choice text was altered. |
| 2026-08-28 | Plan-vs-built review: 0005 option B's cross-reference to "design-spec § 17.6" — a subsection the ARCHITECTURE consolidation dropped — repointed to design/adapters.md § 1 and its sentence rewritten for clarity, argument unchanged. A repo-wide sweep found no other cited section number missing from the merged file. |
| 2026-08-28 | Calendar-effort phrasing removed on the architect's instruction — development here is not paced in human days or weeks, so "two-day" came off the 0003 spike (in the recommendation and Choice) and "one-week" off the 0009 evaluation. The review round 2 memo below keeps its original wording; it is a historical record of what the reviewer wrote. |
