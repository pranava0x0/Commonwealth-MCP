# Spec: Provenance and Evidence Envelope

**Plugs into:** architecture.md § 10 (Provenance and Evidence Contract), § 22 (Error Model), § 16 (Resources)
**Status:** Draft for review, revised 2026-08-26 after the architecture review (architecture.md Part 2 review round 2 § 2.1-2.3): coverage became independent dimensions, evidence references became explicit, and the wire placement became a published-schema commitment. Field names are proposals until Gate A (canonical model freeze).
**Why this exists:** Of the MCP servers surveyed, commercial and civic, none return source provenance with their results (../research/README.md part 4, "What did NOT show up"). Government data needs it. A zoning answer that cannot name the county system it came from, and the date it was fetched, will not support a decision anyone has to defend. Every other contract in this repo depends on this one.

---

## 1. The envelope

Every semantic tool returns exactly this shape. No tool returns a bare list, a bare string, or an ad-hoc object.

```json
{
  "data": {},
  "provenance": [],
  "evidence": [],
  "coverage": {},
  "warnings": [],
  "next_actions": [],
  "resources": []
}
```

| Field | Type | Required | Purpose |
|---|---|---|---|
| `data` | object | yes | The answer, in the tool's documented result schema; material records carry `evidence_refs` |
| `provenance` | array of SourceEntry | yes, may be empty only on total failure | The sources consulted |
| `evidence` | array of Evidence | yes when `data` carries records | The retrieved records claims rest on, each linked to a source |
| `coverage` | Coverage | yes | The five dimensions of what was and was not searched (§ 3) |
| `warnings` | array of Warning | yes, often empty | Caveats that change interpretation |
| `next_actions` | array of NextAction | no | Machine-readable escalation hints for skills |
| `resources` | array of ResourceRef | no | Handles to full payloads too large for context (backend per architecture.md decision 0013) |
| `requires_user_choice` | boolean | no (absent = false) | Set when `data` carries candidates awaiting a human decision (ambiguous jurisdiction/entity); the model must present them, never self-select (architecture.md decision 0004, Chosen) |

The envelope is versioned as a whole: `envelope_version` is carried in execution provenance (§ 4), not in the body, so the body stays clean for the model.

### 1.1 Token budget

Community-measured failure mode: raw tool dumps consume 25K+ tokens per call and starve the model (../research/README.md part 4 § 1, § 7). Rules:

1. `data` targets ≤ 2,000 tokens serialized. Soft limit, enforced by contract test with a small allowlist of exceptions (each with a stated reason).
2. A result set larger than the budget returns: `record_count`, up to N exemplar records (N documented per tool, default 5), aggregate fields the tool documents, and a `resources` handle to the full set.
3. Exemplar selection is deterministic and documented per tool (first-N by the tool's default sort). Never random.
4. `provenance` compresses by source, never by dropping a source: one entry per (source, dataset) pair actually consulted, not per record.

## 2. Provenance entries and evidence references

Two linked levels, so a mixed-source result can prove which source supports which record (the review's § 2.2 requirement — per-source entries alone cannot):

**Source entries** — one per source system consulted, including sources that failed (their failure is recorded in `coverage.source_failures`, their identity here). Each carries an `id` local to the response (`source_01`).

**Evidence objects** — one per retrieved record or record-set that any material fact rests on, each with an `id` (`evidence_01`) and a `source_ref` naming its source entry. Every material record in `data` (a planning case, a chronology event, a finding) carries `evidence_refs: [...]`; a record with no evidence ref is a contract-test failure, which is what makes the skill-level evidence matrix mechanically checkable.

> **Divergence found 2026-08-28, resolved 2026-08-29 in favour of the spec.** The shipped wire emitted a singular `evidence_ref` string per record. The array is what the review round 2 § 2.2 shape adopted here always intended, and the migration ran while the wire had zero external consumers. The contract tests were the reason the drift survived: they were written from the code rather than from this section, so they passed on the wrong shape. The replacements read the field name out of this file.
>
> The live case that needed it shipped in the same change: a PIN matching several parcel polygons is intersected against all of them (bounded at five) and the districts are the union, so each district names every polygon it rests on. Before, the caller was told how many polygons matched and given the zoning of the first — right about the count, silent about the rest of the ground.

```json
{
  "provenance": [
    {
      "id": "source_01",
      "source_id": "va-fairfax-zoning",
      "publisher": "Fairfax County Department of Planning and Development",
      "system": "arcgis",
      "dataset": "Zoning_Districts layer 4",
      "jurisdiction": "va:fairfax-county",
      "authority_level": "primary",
      "access_path": "live",
      "source_updated_at": "2026-08-20T04:00:00Z",
      "retrieved_at": "2026-08-26T14:03:11Z",
      "cache_age_seconds": 0
    }
  ],
  "evidence": [
    {
      "id": "evidence_01",
      "source_ref": "source_01",
      "record_id": "OBJECTID:48291",
      "locator": "https://www.fairfaxcounty.gov/...",
      "retrieved_at": "2026-08-26T14:03:11Z",
      "transformations": ["field_mapping:v3", "crs:EPSG3857->EPSG4326"],
      "payload_hash": "sha256:...",
      "raw_recovery": "available"
    }
  ]
}
```

Evidence field rules: `locator` is a stable human-openable URL when one exists and is omitted (never guessed) when the platform cannot produce one — a wrong link is worse than no link (BetaNYC lesson, ../research/README.md part 5 § 5). `payload_hash` is present when raw retention is permitted; `raw_recovery` is `available | forbidden_by_terms | expired`, with the reason carried so "why can't I see the raw record" always has an answer. `access_path` on the source entry is `live | cache | index` — a result served from a local index (future Legistar-style adapters) must say so and carry the index vintage in `source_updated_at`.

Source-entry field rules:

- `source_id` is the manifest ID from the Government Source Registry. Every provenance entry must resolve to a registered source; a tool that touched an unregistered endpoint is a bug by definition.
- `authority_level` comes from the source manifest, one of `primary | official_secondary | official_derived | third_party | unverified`. Tools copy it; they never compute it. Aggregated external sources (Data Commons-style) are classified per capability, not once per server.
- `source_updated_at` is the publisher's own freshness claim where the platform exposes one (ArcGIS `editingInfo.lastEditDate`, Socrata `rowsUpdatedAt`); `null` with a warning when unavailable, never guessed.
- `retrieved_at` vs `cache_age_seconds`: `retrieved_at` is when the bytes left the government server; cache age says how stale Commonwealth's copy is. Both, always, so "fresh answer from a stale cache" is visible. These fields are the freshness contract — MCP's `ttlMs`/`cacheScope` apply to list/read results and result *resources*, not ordinary `tools/call` results, so protocol cache hints cannot replace them (review § 2.3 correction).
- `transformations` (on evidence objects) names each mapping/reprojection/normalization applied, with the mapping version. Raw source fields remain available through a `resources` handle (`commonwealth://evidence/...`) when `include_raw` is requested and classification permits (design/security-and-data-handling.md § 3).

## 3. Coverage

Coverage answers: if the result is empty or small, is that the world, or the search? The 2026-08-26 review showed the original single `status` enum (`complete | partial | no_coverage | failed`) conflated four independent questions, so coverage is now dimensions, each answering exactly one:

```json
{
  "registry": "covered",
  "execution": "partial",
  "pagination": "complete",
  "source_claim": "unknown",
  "result": "hit",
  "jurisdictions_searched": ["va:fairfax-county", "va:loudoun-county"],
  "jurisdictions_unavailable": [
    {"jurisdiction": "va:prince-william-county", "reason": "no_registered_source"}
  ],
  "time_range": {"from": "2020-01-01", "to": null},
  "source_failures": [
    {"source_id": "va-loudoun-planning", "error": "SourceUnavailable",
     "detail": "HTTP 503 after 3 retries"}
  ],
  "known_limitations": ["va-fairfax-zoning excludes pending rezonings"]
}
```

| Dimension | Values | The question it answers |
|---|---|---|
| `registry` | `covered \| partial \| none \| unknown` | Does the Source Registry cover the requested place/capability/time at all? |
| `execution` | `complete \| partial \| failed` | Did the queries that should have run actually finish? |
| `pagination` | `complete \| truncated \| unknown` | Was the record set fully paged? |
| `source_claim` | `complete \| partial \| unknown` | Does the publisher itself claim a complete record set? (From manifest `known_limitations`; usually `unknown`.) |
| `result` | `hit \| empty` | Did anything match? **Empty is a successful state, not an error.** |

Reading rules the bench enforces (design/bench.md):

- "No records exist" may only be said when `registry: covered`, `execution: complete`, `pagination: complete`, `result: empty`.
- `registry: none` means "Commonwealth has no source for this" — the answer names the gap and where a human would look, never "no results."
- `execution: partial` means named sources could not be checked; the answer says which.
- No rollup field exists; collapsing dimensions back into one status is the failure mode this shape exists to prevent. Whether a deterministic, generated one-sentence `coverage_note` helps smaller models read the dimensions is an open question (§ 10) to settle with Tier-2 evals, not by default.

## 4. Execution provenance

Carried per response, distinguishable from data provenance, primarily for logs and evals rather than the model:

```json
{
  "server": "commonwealth-geo",
  "server_version": "0.3.1",
  "tool": "geo.find_zoning",
  "tool_contract_version": "1",
  "envelope_version": "1",
  "adapters": {"arcgis": "0.4.0"},
  "registry_revision": "2026-08-26T00:00:00Z",
  "request_id": "01JXYZ..."
}
```

### 4.1 Wire placement is a published schema, not a convention

One JSON Schema (versioned with the envelope, shipped in-repo and generated into docs/reference/) defines exactly where everything lives on the MCP wire, so no tool author decides placement (review § 2.3):

- The envelope is the tool result's `structuredContent`; the human-readable `content` block carries a short rendering of `data` plus the coverage reading, generated, never hand-assembled per tool. (The generated rendering is unbuilt as of 2026-08-28; the SDK's default serialization stands in, and this line remains the contract.)
- Execution provenance rides inside `structuredContent` under the reserved `_execution` key — the one underscore-prefixed key, signaling "not part of the answer."
- MCP `resultType` is `"complete"` for ordinary results; `"input_required"` appears only if/when architecture.md decision 0004 layers MRTR on.
- MCP `isError: true` carries only § 7 total failures; the envelope still rides along with `coverage.execution: "failed"`.
- Result handles appear both as envelope `resources` entries and as MCP resource links, same URIs.
- Protocol `_meta` carries only protocol-defined keys (version, OTel trace context); nothing Commonwealth-specific hides there.
- `ttlMs`/`cacheScope` appear where the protocol defines them — list results and `resources/read` responses (result resources declare them from source-manifest hints) — and never as envelope fields.

## 5. Warnings

Structured, typed, and few. A warning changes how the reader should use the data; anything else is noise.

```json
{"code": "screening_only",
 "message": "GIS zoning is a screening layer; the adopted zoning ordinance controls.",
 "source_id": "va-fairfax-zoning"}
```

Initial warning codes: `screening_only`, `stale_source` (source's own update cadence missed), `boundary_precision` (parcel/boundary geometry generalized), `alias_match` (entity matched via alias, not exact ID), `mixed_vintages` (results combine different as-of dates), `terms_note` (source terms constrain reuse).

Four more codes were added during implementation without the review the rule below requires; this note, added 2026-08-28, records them: `freshness_unavailable` (publisher exposes no update date; the envelope says so instead of guessing), `sensitive_public_data` (allowlisted fields withheld per classification), `insecure_transport` (a manifest-declared HTTP-only source), `truncated_inline` (more records retrieved than shown, count and narrowing advice attached).

Codes are an enum in Commonwealth Core; adding one is a reviewed change, and every code's definition text is a spec that the dataset can be grepped against (a record matching a code's own example phrasing must carry that code).

## 6. next_actions

Escalation hints that skills consume (architecture.md § 18). Machine-readable, advisory, never auto-executed:

```json
{"finding": "parcel_intersects_flood_zone",
 "suggested_capability": "environment.screen_flood",
 "reason": "Zoning result geometry intersects FEMA zone AE"}
```

Rules: a `next_action` names a capability, not a tool on a specific server, so routing stays with the Hub; at most 3 per response; the bench scores whether skills follow them when warranted and ignore them when not.

## 7. Error model integration

Typed errors (architecture.md § 22) surface inside the envelope, not instead of it, and the taxonomy shrank with the coverage redesign: `NoResults` and `PartialResults` are no longer errors — an empty match is `coverage.result: "empty"` and a partial run is `coverage.execution: "partial"`, both successful responses. Errors are reserved for conditions that prevent a valid answer (`SourceUnavailable`, `InvalidQuery`, `AmbiguousEntity`, `TermsRestricted`, ...). A failed source inside an otherwise-successful call goes to `coverage.source_failures`. A totally failed call still returns the envelope with `coverage.execution: "failed"` plus the typed error in MCP's `isError` result, message formatted for the model: error class, what it means, what to try.

```text
SourceUnavailable: Loudoun County's planning ArcGIS service did not respond
(3 attempts). This is an outage, not an empty result. Options: retry later;
query va:fairfax-county only; or use registry.source_status to check health.
```

Error strings never include stack traces, internal hostnames, or credentials.

## 8. Worked examples

### 8.1 Simple hit (zoning lookup)

`data` carries the district, description, and overlay list; one provenance entry (Fairfax ArcGIS, primary); coverage `complete` with one jurisdiction; one `screening_only` warning; no resources.

### 8.2 Multi-county search with one outage

`data` carries 14 planning cases (each with `evidence_refs`) and `record_count: 14`; two source entries; coverage `{registry: covered, execution: partial, pagination: complete, result: hit}` with `source_failures` naming Loudoun; warning `mixed_vintages` because the two counties' `source_updated_at` differ by 6 days; `resources` carries the full GeoJSON handle.

### 8.3 The trap the bench enforces

Question: "solar permits in Craig County". No registered Craig County permit source exists. Correct envelope: `data` empty, coverage `{registry: none, execution: complete, result: empty}` with `jurisdictions_unavailable` naming `va:craig-county` / `no_registered_source`, `next_actions` suggesting `registry.search_sources`. Any tool that answers this with `registry: covered` and a bare empty result fails the bench.

### 8.4 Conflicting official records

Two official sources disagree (locality parcel layer vs. statewide VGIN aggregate). `data` presents both values labeled by source; a `comparison` block names the agreement or disagreement; provenance carries both entries with their authority levels; the tool does not pick a winner (architecture.md § 28: return the conflict). (Renamed 2026-08-28 from this spec's proposed `conflict` to the shipped `comparison` — the block appears on agreement too, which architecture.md decision 0005 as Chosen requires, so the shipped name is the accurate one.)

## 9. Testing hooks

- **Contract tests:** every tool's result validates against the wire schema (§ 4.1) plus the tool's own `data` schema. Schemas live in Commonwealth Core; tests iterate the tool registry, never a hand-typed tool list.
- **Evidence completeness:** every material record in every fixture's `data` resolves its `evidence_refs`, and every evidence object resolves its `source_ref`; an unreferenced claim fails.
- **Golden fixtures:** each worked example above exists as a fixture; adapters replay recorded source responses so the assertions are byte-stable.
- **Coverage-honesty tests:** for each domain server, fixtures spanning the dimension combinations that matter — the § 8.3 registry-gap trap, an execution-partial outage, a truncated pagination, and a clean empty — asserting the exact dimension values, not a rollup.
- **Token-budget test:** serialized `data` for every fixture stays under budget or is on the documented exception list, and the test prints the measured sizes so the numbers stay falsifiable.

## 10. Open questions (for the architect)

1. ~~Per-record provenance for mixed chronologies?~~ **Resolved 2026-08-26** by the evidence-reference model (§ 2): records carry `evidence_refs`, evidence carries `source_ref`.
2. Is `cache_age_seconds` enough, or do skills need the cache policy itself (TTL, trigger) surfaced?
3. Where a source's terms forbid redistribution of raw payloads, does `include_raw` return a refusal warning or omit the option entirely? Leaning: refusal warning with `terms_note`, so behavior is explainable. `raw_recovery: forbidden_by_terms` (§ 2) now carries the state either way.
4. Does a generated one-sentence `coverage_note` help smaller models read the five dimensions, or does it become the rollup-by-the-back-door? Settle with Tier-2 evals during the contract spike.
