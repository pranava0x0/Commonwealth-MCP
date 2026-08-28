# Spec: Domain Servers and Tool Contracts (V1: registry, geo, civic)

**Plugs into:** Design Spec § 7 (Server Boundaries), § 27 (Tool Contract Guidelines), § 15 (Toolsets)
**Status:** Draft for review. Tool names below are proposals; each tool's full contract page is generated into docs/reference/ once code exists.
**Why this exists:** The design spec names the servers and sketches tool lists; this spec fixes the conventions every tool follows and trims V1 to contracts that can actually be built against Phase 1 sources. The survey's tool-design taxonomy (RESEARCH.md part 3 § 3) shapes the split: semantic composites at the user surface, composable primitives beneath, both exposed.

---

## 1. Conventions (all tools, all servers)

1. **Naming:** `domain.verb_noun`, lowercase; verbs from a short controlled list (`resolve`, `find`, `search`, `get`, `screen`, `intersect`, `buffer`, `query`). `find` returns entities by criteria; `search` is text-forward; `get` takes an exact ID; `screen` returns constraint findings with explicit screening-only framing.
2. **Arguments:** semantic, few, typed. `jurisdiction` accepts names, FIPS, or `va:` IDs and resolves through the jurisdiction model everywhere it appears — one resolution code path, not per-tool parsing. `location` accepts address | point | parcel-ref uniformly. Date ranges are `{from, to}` ISO dates, never platform-specific formats. No vendor pass-through parameters on semantic tools (design spec § 27's `where`/`outFields` ban).
3. **Every response is the envelope** (design/provenance-envelope.md), concise by default; `detail: "full"` opts into more per Anthropic's measured concise/detailed guidance.
4. **Descriptions follow the template** in design/docs-practices.md § 3, each with a when-NOT clause naming the better tool; descriptions are bench-covered artifacts.
5. **Ordering:** tool registration order is explicit and stable per server (contract-tested), for prompt-cache friendliness.
6. **Deprecation aliases from day one:** the alias table exists (empty) in core; renames are additive with aliases, per the github-mcp-server mechanism.
7. **Toolsets:** each server declares `default` (the small daily-driver set) plus named extras; `discovery` (registry tools) and `spatial` (geo primitives) stay out of `default` per DECISIONS.md 0001.

## 2. `commonwealth-registry` (toolset: `discovery`)

| Tool | Contract sketch |
|---|---|
| `registry.resolve_jurisdiction` | design/jurisdiction-resolution.md § 2, in full |
| `registry.search_sources` | text + jurisdiction + capability filters over manifests; returns manifest summaries with lifecycle/authority; proposed sources included, labeled |
| `registry.describe_source` | one manifest, formatted for reading, terms and limitations prominent |
| `registry.source_status` | health/degraded state, last-verified, recent probe history |

`find_authoritative_source` from the design spec folds into `search_sources` (an `authoritative_only` flag) rather than being a separate tool — one search surface, fewer near-duplicate choices for the model. `list_capabilities` becomes a resource (`commonwealth://capabilities`), not a tool: it's static vocabulary, exactly what resources are for.

## 3. `commonwealth-geo`

Composites (in `default`): `geo.resolve_location`, `geo.find_parcel`, `geo.find_zoning`, `geo.find_boundaries`.
Primitives (toolset `spatial`): `geo.intersect`, `geo.buffer`, `geo.find_nearby`, `geo.query_source` (the registered-source escape hatch, design spec § 12.2).

- Primitives follow osmmcp's five principles verbatim (uniform parameter names, single responsibility, output-as-input compatibility, no side effects, precise errors); the checklist lives in the geo package docstring and reviewers apply it.
- Composites follow DECISIONS.md 0005 as **Chosen (architect override, 2026-08-26)**: no ranking, no mode parameter. A composite queries the **top two known-authoritative sources** for the capability in the resolved jurisdiction (`authority_level` decides which two, never a single winner) and always surfaces the per-source results — agreement or conflict — in `data`, with both sources in `provenance`. Where only one registered source exists, one is queried and coverage says so.
- `find_zoning` and friends return the district plus overlay/floodplain flags *as findings with `next_actions`*, never as conclusions; the screening-only warning is structural (envelope § 5), not prose goodwill.
- Geometry in results: simplified inline, full behind a resource, always 4326 (design/adapters.md § 3).
- V1 sources: VGIN, Fairfax, Loudoun, Richmond via `arcgis`; parcel lookup routes locality-first per DECISIONS.md 0005's default until the authority table says otherwise.

**`geo.find_boundaries` shipped 2026-08-28** against a new statewide
source (VGIN Administrative Boundaries, `boundary.lookup`). It follows the
geometry rule above as far as the missing piece allows: geometry is
server-side generalized to 0.0002 degrees and returned only at
`detail: "full"`, because the result-resource store that would hold the
unsimplified polygon does not exist yet (DECISIONS.md 0013, backlog). Concise —
the default — returns bbox, centroid, area, and vertex counts, which keeps
it inside the envelope's 2000-token data budget. The same source backs
point-in-polygon jurisdiction resolution
(design/jurisdiction-resolution.md § 2), so one onboarding closed two
milestones. Two real publisher quirks it surfaced are recorded in
KNOWN_SOURCE_QUIRKS.md rather than normalized away.

`geo.resolve_location` and the `spatial` primitives
(`intersect`, `buffer`, `find_nearby`, `query_source`) remain unbuilt.
`resolve_location` is blocked on the same registered-geocoder prerequisite
as address-based jurisdiction resolution.

## 4. `commonwealth-civic` (second milestone — after the geo vertical's beta exit)

Re-sequenced 2026-08-26: the review is right that proving one complete path beats two half-built domains, so civic starts after the geo vertical ships (DECISIONS.md review round 2 § 6). The contracts below stand as the target.

`default`: `civic.search_legislation`, `civic.get_bill`, `civic.search_law`, `civic.search_meetings`.
Extras (toolset `civic-full`): `civic.get_vote`, `civic.get_agenda_item`, `civic.search_regulations`.
Deferred beyond V1 (contracts drafted when their sources onboard): campaign finance, election results — both need source-terms review before any contract is worth writing.

- `get_bill` returns status as of retrieval with LIS's own timestamps; bill version identity (introduced/engrossed/enrolled) is explicit in the result, because conflating versions is the domain's classic error.
- `search_law` (Code of Virginia) results carry section citations and effective dates; amendments-pending surfaces as a warning when LIS shows a bill touching the section, which is the cross-tool join the two V1 skills exercise.
- Meetings: Phase 1 covers the localities whose agenda platforms have registered manifests (legistar adapter lands here); coverage honesty does the rest.

**First slice shipped 2026-08-28, ahead of the LIS bill-tracking surface:**
`civic.get_code_section` — direct Code of Virginia citation lookup, not
`search_law`. LIS's own JSON/XML API (bills, members, full-text search)
needs an API key this project hasn't registered for (backlog.md); the
public HTML pages at law.lis.virginia.gov don't. The tool reads those
pages directly (a new `virginia_law` adapter type, `html.parser`-based,
no new dependency) rather than waiting on the key. It is named for what
it actually does — direct citation lookup — not `search_law`, since
there is no full-text search behind it; the design sketch's name would
overclaim. `search_law`, `get_bill`, and the rest of the civic default
toolset stay on the LIS-key-registration prerequisite named in
backlog.md.

## 5. What deliberately does not exist in V1

Finance, infrastructure, environment, people servers stay at design-spec sketch level; their tool lists are not contracts yet, and writing them before their sources are registered would freeze guesses (base-files: data assumptions are guesses until queried). The design spec's lists remain the shape for those phases; each gets a contract page in this spec's format when its Phase begins. NEPA-MCP federation covers the environmental screen in the meantime via the external-catalog entry (design/hub-catalog.md § 1).
