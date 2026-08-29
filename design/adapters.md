# Spec: Adapter Layer

**Plugs into:** architecture.md § 12 (Adapter Layer), § 3.2 (Semantic Tools, Boring Adapters)
**Status:** Draft for review.
**Why this exists:** Adapters are the boring, load-bearing floor: generic clients for the platforms Virginia governments actually run (ArcGIS everywhere, Socrata for data.virginia.gov, assorted OpenAPI/CSV/HTML). The survey found no maintained generic adapter libraries worth importing wholesale — the ArcGIS/Socrata MCP field is fragmented single-purpose wrappers (../research/README.md part 3 § 2) — so these get built here, small, against the design-spec contract.

---

## 1. Contract (all adapters)

```python
class Adapter(Protocol):
    def describe(self, manifest: SourceManifest) -> SourceDescription: ...
    def query(self, manifest: SourceManifest, q: Query) -> AdapterResult: ...
    def paginate(self, cursor: Cursor) -> AdapterResult: ...
    def health(self, manifest: SourceManifest) -> HealthReport: ...
    params_schema: ClassVar[JSONSchema]     # validates manifest `adapter:` block
    probe_types: ClassVar[dict[str, Probe]] # health probes it offers
```

Rules, several lifted straight from research findings:

1. **Read-only by construction.** Adapter clients are built without write verbs (no POST-to-mutate paths exist to call) — Supabase's data-layer enforcement idea applied at the client boundary. A future write adapter is a different class in a different package behind Gate F.
2. **Adapters never rank, never interpret.** Authority, freshness policy, and semantics live in manifests and core; an adapter that knows "locality beats VGIN" is a bug (architecture.md decision 0005; skills.md § 4 states the same rule for skills — repointed 2026-08-28 from "architecture.md § 17.6", a subsection the consolidation dropped).
3. **Typed errors at the boundary.** Every failure normalizes to the § 22 error set before leaving the adapter; raw platform errors ride along as detail. Emptiness is not an adapter concept — adapters report what the platform returned; the coverage dimensions (`result: empty` vs `registry: none` vs `execution: partial`) are core's job to assemble.
4. **TTL caching inside the adapter layer**, keyed by (manifest, query), honoring manifest `ttl_hint_seconds` — osmmcp's pattern in front of rate-limited public endpoints, and the source of the envelope's `cache_age_seconds`.
5. **Politeness budget per source**: concurrency caps and backoff per manifest host; government endpoints are shared civic infrastructure and Commonwealth must be a courteous client. Rate-limit hits surface as `RateLimited` with retry-after when the platform says.
5a. **Egress policy is enforced here**: adapters are the only outbound path, and every request passes the security-and-data-handling.md § 2 checks (registered hosts only, private/metadata ranges refused with connect-time DNS recheck, bounded redirects with credential stripping, response/decompression caps). Each rule has a refusal fixture in the security test tier.
6. **`params_schema` makes manifests validatable** (design/source-registry.md § 1 rule 3): the manifest validator imports each adapter's schema, so a typo'd layer ID fails at validation, not at first query.

## 2. Initial adapters (Phase 0-1)

| Adapter | Platforms it covers | The hard part to get right |
|---|---|---|
| `arcgis` | Nearly every VA locality GIS + VGIN + VDOT services | Field/schema variance across localities; pagination (`resultOffset` vs `exceededTransferLimit`); geometry precision + CRS normalization to EPSG:4326; `editingInfo.lastEditDate` for freshness; query `where` construction from typed filters only |
| `socrata` | data.virginia.gov + peer portals | SoQL construction from typed filters; `rowsUpdatedAt` freshness; app-token-optional politeness (keyless works, throttled) |
| `openapi` | Assorted state agency APIs (LIS services, others) | Spec-driven but *manifest-scoped*: only operations the manifest names are callable, never the whole spec surface |

Phase 2 candidates unchanged from the design spec (`ogc`, `gtfs`, `open311`, `municode`, `legistar`, `csv_json`, `html_download`), each added when a registered source needs it, never speculatively. `html_download` is bulk-file retrieval (posted CSVs/PDFs), not scraping; anything resembling scraping routes through the § 20 terms gates and Gate B.

Design notes banked from the 2026-08-26 tools research (../research/README.md part 5) for when these land:

- `legistar` follows BetaNYC's two-speed shape: local index for search/history/aggregation, live API for current status and upcoming meetings — with `access_path: index` and index vintage on every indexed result, live confirmation required for anything current, ambiguous bare identifiers returning candidates, and no human links emitted unless the platform can actually produce them (a wrong link is worse than none). Locality-specific matter types stay as source vocabulary, not a premature shared enum.
- `gtfs` manifests need fields the generic schema lacks: agency timezone (correctness of "now"), static-schedule cadence vs realtime feed classes on separate TTLs, feed-health as a first-class capability, and cold-start/first-download size as acceptance criteria.

## 3. Spatial specifics (`arcgis` first)

- Geometry operations follow a split: **push down** what the platform does well (spatial intersect via ArcGIS query geometry) and **compute locally** what it doesn't (buffers via Shapely when the service lacks them), with the choice recorded in `transformations` so results are explainable.
- One CRS at the contract boundary (EPSG:4326, GeoJSON); adapters own reprojection and record it.
- Geometry simplification for envelope-sized responses is a documented, versioned transformation; the full-precision geometry lives behind the result resource, never silently discarded.

## 4. Testing

Per testing-and-demos.md: unit + contract per adapter, recorded fixtures from real Virginia endpoints, resilience tests simulating the platform's actual failure modes (ArcGIS's 200-with-error-body habit is a named fixture, not a surprise), and the reconciliation audit replaying fixtures against live services on schedule. The known-quirks register (`source-quirks.md`, repo root) is expected to fill up with ArcGIS locality variance first; that accumulation is the adapter layer doing its job in the open. The register held four entries as of 2026-08-28.
