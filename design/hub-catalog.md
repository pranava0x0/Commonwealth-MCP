# Spec: Hub and MCP Catalog

**Plugs into:** Design Spec § 14 (MCP Hub / Control Plane), § 15 (Toolset Exposure)
**Status:** Draft for review. The Hub is Phase 3; this spec exists now so earlier phases don't foreclose it.
**Why this exists:** The Government Source Registry answers "what public systems exist"; the Hub catalog answers "what Commonwealth servers exist, where they run, what they expose, and who may use them." GSA's hub catalog is the structural model; the 2026 protocol changes (statelessness, extensions field, registry-as-aggregator-feed) simplify what the Hub must do.

---

## 1. Catalog entry schema (internal, richer than any export)

One YAML per server in `catalog/servers/`:

```yaml
id: commonwealth-geo
display_name: Commonwealth Geo
version: 0.3.1
protocol_revisions: ["2026-07-28", "2025-11-25"]   # what the deployment actually serves

runtime:
  remote:
    endpoint: https://mcp.commonwealthmcp.org/geo/mcp
    health: https://mcp.commonwealthmcp.org/geo/health
  local:
    package: {registry: pypi, name: commonwealth-mcp, extra: geo}
    command: "commonwealth serve --servers geo"

tenancy: shared            # shared | per-user
access:
  classification: public
  read_only: true
  auth: none               # none | oauth | ema

toolsets:
  default: [geo.resolve_location, geo.find_parcel, geo.find_zoning, geo.find_boundaries]
  spatial: [geo.intersect, geo.buffer, geo.find_nearby]
  expert: ["*"]

capabilities:              # capability-vocab IDs this server can route, derived at build
  - zoning.lookup
  - parcel.lookup

depends_on:
  source_capabilities: [zoning.lookup, parcel.lookup]   # satisfied by the source registry

risk: low
```

Rules:

- `capabilities` and `toolsets` are generated from the server's own tool registry at build time and committed; a drift test regenerates and diffs, so the catalog cannot quietly disagree with the code (the mirrored-list rule from base-files/CLAUDE.md, applied to the catalog).
- Exports are derived artifacts: official MCP Registry `server.json`, GSA/Obot-format entries if federal federation ever wants them, client config snippets for the docs (`claude mcp add ...`), and the plugin/bundle manifests. One generator, many formats; none hand-maintained.
- External servers Commonwealth recommends but does not operate get entries under `catalog/external/` with `operated_by: external` and no runtime block beyond the public endpoint. Each entry additionally declares (2026-08-26 review § 4.3, tools research § 10):
  - `integration_mode: native-external | commonwealth-wrapper` — catalog registration does NOT make a foreign server speak Commonwealth envelopes; either the consuming skill understands the foreign contract as-is, or a maintained wrapper translates it, and the entry says which.
  - `authority_by_capability` — aggregated sources are classified per capability, not once per server (Data Commons is `official_derived` for statistics and unsuitable for local proceedings; its entry says so).
  - A conformance check in the release suite for any external server a shipped skill depends on: replay one recorded call per depended-on capability and diff against the recorded contract, so a foreign contract change fails a Commonwealth release instead of a user's session.
  - Current planned entries: PNNL NEPA-MCP (native-external), GPO GovInfo (`https://api.govinfo.gov/mcp`, public preview, api.data.gov key, native-external with per-release compatibility check), Data Commons MCP (native-external, derived-statistics only), Census Bureau MCP (cataloged; V1 prefers direct Census API adapters over its Docker/Postgres install), OpenStates MCP (third-party, discovery fallback only — never authority for Virginia status). Details: RESEARCH.md part 5.

## 2. Toolset exposure mechanics

Tool budgets are DECISIONS.md 0002's: 8-12 per profile, ceiling 20, enforced by `core/toolreg.py`. (The community's broader 15-25 comfort measurements are in RESEARCH.md part 4 § 1; 0002 chose tighter.) Mechanics:

- Every server ships `default` (small, the daily-driver reads), optional named task profiles, and `expert` (everything). Profiles across servers ("development" = registry.default + geo.default + civic.legislation) compose into a client-facing endpoint or config.
- **Capability routing does not wait for the Hub** (2026-08-26 review § 4.1): from V1, capability-to-tool bindings generate from the capability vocabulary + tool registries into one routing table; `commonwealth serve --profile <name>` and `commonwealth configure <client> --profile <name>` activate a profile locally; startup fails loudly when a skill-required capability has no route or an unresolved duplicate route. The Phase-3 Hub consumes this same table; it does not invent routing. **Built so far (2026-08-28):** `serve --profile` with hand-written profiles, the 20-tool ceiling, and unknown-profile refusal; capability→*source* routing lives in `SourceRegistry.select()`. The generated capability→tool table, `configure`, and the startup capability check are not built — the last has nothing to check until the first skill declares required capabilities, which is where profile generation from skill metadata (0002) lands too.
- Tool ordering deterministic everywhere (protocol SHOULD + prompt-cache economics).
- Tool search interop: profiles beyond the default sizes should assume clients may defer-load; nothing in Commonwealth requires a client to hold the full surface. When the protocol's server-side progressive discovery lands (roadmap), the Hub adopts it and per-client toolset gymnastics shrink; the catalog schema already records per-revision support to stage that migration.

## 3. Deployment posture

- V1 (pre-Hub): no gateway at all. Local stdio via the package, or single-tenant Streamable HTTP per server. The catalog file generates the client-config docs (not yet written as of 2026-08-28 — no `catalog/` directory exists; it lands with `configure`, its first consumer); the Hub is a consumer of the catalog, not its prerequisite.
- Phase 3 evaluates gateway options against what then exists (DECISIONS.md 0009 records the criteria rather than a premature pick: protocol-revision support, EMA readiness, health/routing, cost of operation). Statelessness removes session affinity from the requirements list entirely, which widens the viable-gateway field and keeps plain reverse proxies in contention.
- `/health` per server returns version, protocol revisions, source-registry revision, and per-source degraded counts; the Hub aggregates but never reinterprets.

## 4. Tenancy and credentials

V1 is `shared` + `auth: none` everywhere by design. The schema carries `per-user` and `auth: oauth|ema` so Phase 5 is a data change plus review at Gate D, not a schema redesign. Credential material never appears in the catalog; per-user modes name the identity requirement, and the EMA extension (stable, thin client support so far) is the target pattern for institutional access (RESEARCH.md part 1 § 7).
