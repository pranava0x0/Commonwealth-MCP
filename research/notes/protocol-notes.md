# MCP Protocol Research Notes

Research date: 2026-08-26. All claims sourced; "unverified" marks anything not confirmed via fetch.

## 1. Current MCP Spec

**Latest released protocol revision: `2026-07-28`.** This is a major, breaking redesign relative to `2025-06-18`. Source: https://modelcontextprotocol.io/specification/ (fetched 2026-08-26), which now points to schema at `github.com/modelcontextprotocol/specification/blob/main/schema/2026-07-28/schema.ts`.

There are THREE revisions since 2025-06-18 was current:
- `2025-06-18` (baseline for this research task)
- `2025-11-25` (intermediate)
- `2026-07-28` (current, latest)

Note on the task's registry hint (schema dated 2025-12-11): I have not yet found a spec revision dated 2025-12-11 — the sequence found on modelcontextprotocol.io is 2025-06-18 → 2025-11-25 → 2026-07-28. It's possible the registry's `server.json` schema versioning is decoupled from the protocol spec's own revision dates. Flagged for the registry section (topic 2) and in Unresolved.

### Revision 2025-11-25 (vs 2025-06-18)
Source: https://modelcontextprotocol.io/specification/2025-11-25/changelog (fetched 2026-08-26)

Major changes:
1. Authorization server discovery via OpenID Connect Discovery 1.0 (PR #797).
2. Servers can expose **icons** as metadata for tools/resources/resource templates/prompts (SEP-973).
3. Incremental scope consent via `WWW-Authenticate` header (SEP-835).
4. Guidance added on tool naming (SEP-986).
5. `ElicitResult`/`EnumSchema` reworked to a more standards-based approach; supports titled/untitled, single-select and multi-select enums (SEP-1330).
6. **URL mode elicitation** added (SEP-1036) — server can ask client to open a URL (e.g., for OAuth-like out-of-band flows) as part of elicitation.
7. Tool-calling support added to **sampling** via `tools`/`toolChoice` params (SEP-1577).
8. OAuth **Client ID Metadata Documents** added as a recommended client registration mechanism (SEP-991) — this is the beginning of the move away from Dynamic Client Registration (DCR).
9. **Experimental tasks support** added (SEP-1686) — durable/long-running request tracking via polling and deferred result retrieval. (This was later reworked/moved in 2026-07-28, see below.)

Minor changes: stderr logging clarification for stdio; `Implementation.description` field added (aligned with registry server.json); HTTP 403 required for invalid `Origin` header on Streamable HTTP; input validation errors reclassified as Tool Execution Errors (not Protocol Errors) so models can self-correct (SEP-1303); SSE polling/disconnect semantics (SEP-1699); OAuth Protected Resource Metadata aligned with RFC 9728, `WWW-Authenticate` now optional with `.well-known` fallback (SEP-985); default values allowed in elicitation primitive schemas (SEP-1034); **JSON Schema 2020-12 established as default dialect** (SEP-1613).

Governance (first formalized in this revision): MCP governance structure formalized (SEP-932); community communication practices established (SEP-994); Working Groups / Interest Groups formalized (SEP-1302); **SDK tiering system** established (SEP-1730).

Full diff: https://github.com/modelcontextprotocol/specification/compare/2025-06-18...2025-11-25

### Revision 2026-07-28 (vs 2025-11-25) — CURRENT
Source: https://modelcontextprotocol.io/specification/2026-07-28/changelog (fetched 2026-08-26)

This is a large breaking redesign making MCP fundamentally **stateless and HTTP-native**. Major changes:

1. **Removed protocol-level sessions** — the `Mcp-Session-Id` header is gone from Streamable HTTP. List endpoints (`tools/list`, `resources/list`, `prompts/list`) no longer vary per-connection. Cross-call state, if needed, uses explicit server-minted handles passed as ordinary tool arguments (SEP-2567).
2. **MCP made fully stateless**: the `initialize`/`notifications/initialized` handshake is removed. Every request now carries protocol version and client capabilities in `_meta` (`io.modelcontextprotocol/protocolVersion`, `io.modelcontextprotocol/clientCapabilities`). Clients SHOULD self-identify per request (`io.modelcontextprotocol/clientInfo`); servers SHOULD identify themselves in each result's `_meta` (`io.modelcontextprotocol/serverInfo`). Version mismatches return `UnsupportedProtocolVersionError` (SEP-2575).
3. New **`server/discover`** RPC: servers MUST implement it to advertise supported protocol versions, capabilities, and identity; clients MAY call it up front or as a stdio backward-compat probe (SEP-2575).
4. HTTP GET endpoint and `resources/subscribe`/`resources/unsubscribe` replaced by **`subscriptions/listen`**: one long-lived POST-response stream for opted-in server→client change notifications, scoped per type (`toolsListChanged`, `promptsListChanged`, `resourcesListChanged`, `resourceSubscriptions`), tagged with `io.modelcontextprotocol/subscriptionId`. Request-scoped notifications (`notifications/progress`, `notifications/message`) still flow on the originating request's response stream (SEP-2575).
5. **Removed `ping`, `logging/setLevel`, `notifications/roots/list_changed`.** Log level now set per-request via `io.modelcontextprotocol/logLevel` in `_meta`.
6. **Tasks moved out of core protocol into an official extension** (`io.modelcontextprotocol/tasks`, SEP-2663). Redesigned: blocking `tasks/result` replaced by polling `tasks/get` + new `tasks/update` for client→server input; `tasks/list` removed; servers can return task handles unsolicited (no per-request opt-in needed).
7. **Multi Round-Trip Requests (MRTR)** pattern introduced (SEP-2322), replacing server-initiated requests like `roots/list`, `sampling/createMessage`, `elicitation/create`. Servers instead return `InputRequiredResult` (`resultType: "input_required"`) with `inputRequests`; clients respond via `inputResponses` on a retry of the original request.
8. All results now carry required **`resultType`** field (`"complete"` or `"input_required"`); clients MUST treat results from earlier-protocol servers lacking the field as `"complete"`.
9. **SSE stream resumability and message redelivery removed** (no more `Last-Event-ID`/SSE event IDs) from Streamable HTTP. A broken stream loses the in-flight request; client MUST reissue as a new request with new request ID.

Minor changes: `extensions` field added to `ClientCapabilities`/`ServerCapabilities`; OpenTelemetry trace-context conventions documented for `_meta` (`traceparent`, `tracestate`, `baggage`, SEP-414); servers SHOULD return deterministic tool ordering from `tools/list` (helps prompt-cache hit rates); standard headers `Mcp-Method`/`Mcp-Name` required on Streamable HTTP POST plus `x-mcp-header` support for custom headers from tool params (SEP-2243); **`ttlMs` and `cacheScope` required on list/read results** via new `CacheableResult` interface (`tools/list`, `prompts/list`, `resources/list`, `resources/read`, `resources/templates/list`) — freshness hints + public/private cache scoping (SEP-2549); resource-not-found error code changed `-32002` → `-32602` (Invalid Params, JSON-RPC alignment); `iss` param required in authz responses per RFC 9207, clients MUST validate against recorded issuer (SEP-2468); clients MUST specify `application_type` in Dynamic Client Registration (SEP-837); client credentials MUST be keyed by issuer identifier, no cross-issuer reuse (SEP-2352); `inputSchema`/`outputSchema` loosened to allow any JSON Schema 2020-12 keywords, `structuredContent` allows any JSON value, with `$ref` resolution requirements (SEP-2106); **removed `notifications/elicitation/complete`** and `elicitationId` (both introduced in 2025-11-25) — MRTR replaces the correlation mechanism; new **error code allocation policy** partitioning JSON-RPC server-error range (`-32000`..`-32019` implementation-defined/grandfathered, `-32020`..`-32099` reserved for MCP spec; renumbers `HeaderMismatch`, `MissingRequiredClientCapability`, `UnsupportedProtocolVersion`).

**Deprecated in 2026-07-28** (remain functional during a deprecation window, new implementations should not adopt):
- **Roots, Sampling, and Logging features** deprecated entirely (SEP-2577). Migration guidance: pass directories/files via tool params/resource URIs/server config instead of Roots; integrate directly with LLM provider APIs instead of Sampling; log to stderr (stdio) or use OpenTelemetry instead of Logging.
- **HTTP+SSE transport** (already deprecated since `2025-03-26`) reclassified as formally Deprecated under the new feature lifecycle policy (SEP-2596). Migrate to Streamable HTTP.
- `includeContext` values `"thisServer"`/`"allServers"` (soft-deprecated since `2025-11-25`) now formally Deprecated (SEP-2596); use `"none"` or omit.
- **OAuth 2.0 Dynamic Client Registration (RFC 7591)** deprecated as client registration mechanism in favor of **Client ID Metadata Documents** (PR #2858); DCR remains available for backward compat only.

Governance/process updates in 2026-07-28: adopted a formal **feature lifecycle and deprecation policy** (Active/Deprecated/Removed states, minimum 12-month deprecation window, plus a registry of deprecated features at `/specification/2026-07-28/deprecated`) (SEP-2596); SEP workflow formalized as PR-based with markdown files in `seps/` directory, PR-derived numbering (SEP-1850).

Full diff: https://github.com/modelcontextprotocol/specification/compare/2025-11-25...2026-07-28

### Transports status (as of 2026-07-28)
- **Streamable HTTP**: the current, actively-developed transport. Now stateless (no session header), no SSE resumability.
- **stdio**: still supported. Roadmap (see below) proposes running Streamable HTTP itself over stdio (HTTP/2 framing over stdin/stdout) to unify the two transport pipelines — this is proposed/in-progress work, NOT yet shipped.
- **HTTP+SSE (legacy, pre-2025-03-26 style)**: formally **Deprecated** as of 2026-07-28 (was already deprecated since 2025-03-26; now under the formal lifecycle policy). Should not be used for new servers.

### Authorization status (as of 2026-07-28)
- OAuth 2.1 remains the basis (carried over from earlier revisions — not contradicted in the 2026-07-28 changelog).
- Resource Indicators (RFC 8707) — required of clients since 2025-06-18; no change noted in later changelogs (unverified whether still required verbatim, but nothing in the fetched changelogs rescinds it).
- Protected Resource Metadata — RFC 9728 alignment tightened in 2025-11-25 (WWW-Authenticate now optional, `.well-known` fallback).
- `iss` parameter validation (RFC 9207) required since 2026-07-28.
- Client registration: **Dynamic Client Registration (RFC 7591) is now deprecated** (2026-07-28) in favor of **Client ID Metadata Documents** (introduced 2025-11-25 as a recommended mechanism, SEP-991). DCR still works for back-compat with authorization servers lacking Client ID Metadata Document support.
- Credentials must be keyed per-issuer, no cross-issuer reuse (2026-07-28, SEP-2352).
- `application_type` required in DCR requests (2026-07-28, SEP-837) to avoid OIDC redirect URI conflicts.

### Elicitation status
- Introduced 2025-06-18.
- 2025-11-25: `ElicitResult`/`EnumSchema` reworked (titled/untitled, single/multi-select enums); **URL mode elicitation** added; default values allowed in primitive schemas.
- 2026-07-28: elicitation's server-initiated request mechanism folded into the general **MRTR (Multi Round-Trip Requests)** pattern — `notifications/elicitation/complete` and `elicitationId` (both from 2025-11-25) removed; servers needing correlation across retries must encode their own identifier in `requestState`.

### Structured tool output / outputSchema
- Structured tool output added 2025-06-18 (PR #371).
- 2026-07-28: `inputSchema`/`outputSchema` loosened to allow any JSON Schema 2020-12 keywords; `structuredContent` allows any JSON value (SEP-2106). Roadmap flags that concurrent `content` + `structuredContent` return has caused confusion/diverging implementations and a "Core Primitives WG" is actively redesigning `tools/call` result shape (not yet shipped — see Roadmap below).

### Tool annotations (readOnlyHint, etc.)
- Not covered in the 2025-11-25 or 2026-07-28 changelogs fetched so far — appears unchanged since 2025-06-18. Roadmap mentions "primitive annotations" (audience/priority content annotations) being extended to tool results/resources is under discussion by the Core Primitives WG, and that most implementers haven't adopted the existing annotation mechanism — possible future deprecation being considered. unverified: exact current annotation field list; need to check server/tools spec page directly if time allows.

### Resources + resource links in tool results
- Resource links in tool call results added 2025-06-18 (PR #603). No changes noted in subsequent changelogs.

### Pagination / Completions
- Not mentioned as changed in either 2025-11-25 or 2026-07-28 changelog — appears stable since 2025-06-18. unverified in detail (did not fetch the pagination/completion spec pages directly).

### Tasks / long-running operations
- Added experimentally in 2025-11-25 (SEP-1686).
- **Redesigned and moved to an official extension** in 2026-07-28 (`io.modelcontextprotocol/tasks`, SEP-2663): polling via `tasks/get` replaces blocking `tasks/result`; new `tasks/update` for client-to-server input; `tasks/list` removed; servers may return task handles unsolicited. Per the roadmap, further work is expected "toward eventual inclusion of the extension in the core protocol" — so as of 2026-07-28 Tasks is an **extension**, not core.

### New in 2026-07-28 not otherwise categorized above
- Stateless architecture overall (see major changes above) is the headline change of this revision.
- `server/discover` RPC (new).
- `subscriptions/listen` (new, replaces GET+subscribe/unsubscribe).
- MRTR pattern (new, replaces roots/list, sampling/createMessage, elicitation/create as server-initiated calls).
- CacheableResult (`ttlMs`, `cacheScope`) on list/read results (new).
- Formal feature lifecycle/deprecation policy (new).

### Roadmap (forward-looking, NOT yet shipped)
Source: https://modelcontextprotocol.io/development/roadmap (fetched 2026-08-26, page states "Last updated: 2026-08-22")

Five priority areas for the *next* spec release (roadmap explicitly says "reflects current thinking rather than firm commitments"):
1. **Agentic Messaging Primitives** — server-initiated events/webhooks (Triggers & Events WG), composition review of Tasks/subscriptions/progress so they share one lifecycle/cancellation/error model; continued work on Tasks (SEP-2663) toward core inclusion.
2. **HTTP-Native Transport Unification and Hardening** — "HTTP over stdio" (Streamable HTTP spoken over stdin/stdout via HTTP/2 framing) to unify transport pipelines; caching work extending to ETags for versioning tool call results; standardized error handling; capability scoping for tool lists post-SEP-2575.
3. **Agent Identity and Enterprise-Ready Security** — DPoP finalization (new Agent Identity WG, forming); agent identity/delegation via Workload Identity Federation (SEP-1933), ID-JAG (used by Enterprise-Managed Authorization extension), RFC 8693 token exchange, coordinated with IETF OAuth and WIMSE working groups; human-presence attestation under discussion.
4. **Improved Primitives** — redesign `tools/call` result shape (new Core Primitives WG, forming) to fix content/structuredContent confusion; **"progressive discovery"** — experimental server-side mechanism so clients learn tools/resources on demand rather than ingesting the full catalog upfront (directly relevant to large tool-surface / tool-search concerns); primitive annotations extended to tool results/resources, or deprecated if unused; File Uploads WG continuing on scoped file ops and filesystem-like resource semantics (range reads, hierarchical listing).
5. **Improved SDK Developer Experience** — SDK WG + Core Maintainers defining "the extension contract" (which role — host/client/server/agent — an extension binds, what SDKs must natively support, packaging, versioned capability additions, auth as its own area); an experiment generating a candidate Tier 1 SDK + quickstarts directly from the spec, validated against a conformance test suite.

Roadmap names Core Maintainers per area (e.g., Caitie McCaffrey, Clare Liguori, Peter Alexander, Kurtis Van Gent, Nick Cooper, Paul Carleton, Den Delimarsky, David Soria Parra) — confirms a maintainer/Working-Group governance structure is operating in practice, consistent with governance formalization in 2025-11-25.

## 2. Official MCP Registry (registry.modelcontextprotocol.io)

Sources: https://modelcontextprotocol.io/registry/about, https://modelcontextprotocol.io/registry/quickstart (both fetched 2026-08-26); WebSearch results referencing GitHub's registry repo and truefoundry.com blog (2026, snippet-level only).

**Status: still in PREVIEW, not GA.** Official banner on both the about page and quickstart: "The MCP Registry is currently in preview. Breaking changes or data resets may occur before general availability." Search-result snippets (unverified — not independently fetched from a primary source) additionally claim the REST API itself has entered an "API freeze" at **v0.1** even while the registry as a whole stays preview; the live `curl` example in the quickstart does confirm the API path is versioned `/v0.1/servers`.

Backed by "major trusted contributors to the MCP ecosystem such as Anthropic, GitHub, PulseMCP, and Microsoft" (registry/about page).

### What the registry is / is not
- A **centralized metadata repository**, not a package host. `server.json` metadata points to packages hosted elsewhere (npm, PyPI, Docker Hub, etc.) or to remote server URLs — e.g., a "weather v1.2.0" registry entry maps to `npm:weather-mcp`.
- Does **not** support private servers (internal-network-only servers, or servers on private package registries). Maintainers explicitly recommend self-hosting a private registry for that case, but also state the official registry codebase "is not designed for self-hosting" and won't be supported if forked.
- Not intended for direct consumption by MCP host applications (Claude Desktop, Cursor, etc.). It's meant to be consumed by **downstream aggregators/marketplaces**, which pull periodically (example cadence given: "once per hour") and layer curation/ratings on top. Hosts are expected to consume those aggregators instead, via the registry's own published OpenAPI spec.
- Security scanning is delegated outward: underlying package registries (npm/PyPI/Docker Hub) do their own scanning; downstream aggregators can add more. The official registry itself only does namespace authentication + metadata hosting.

### server.json
Current schema referenced by the CLI-generated template (as of fetch, 2026-08-26): `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`. **This resolves the task brief's discrepancy note**: 2025-12-11 is a **registry schema version**, issued between the two protocol spec revisions 2025-11-25 and 2026-07-28 — it is a separate versioning track from the protocol spec itself, not an undiscovered protocol revision.

Minimum fields shown in the generated template: `$schema`, `name` (reverse-DNS, e.g. `io.github.my-username/weather`), `description`, `repository` (`url` + `source`, e.g. `"source": "github"`), `version`, and `packages[]` (each with `registryType` e.g. `npm`, `identifier`, `version`, `transport.type` e.g. `stdio`, optional `environmentVariables[]` with `description`/`isRequired`/`format`/`isSecret`/`name`).

### Namespacing
Server names use **reverse-DNS format**: `io.github.<username>/<server-name>` (GitHub-authenticated) or `com.example/<server-name>` (DNS-authenticated custom domain). The `name` in `server.json` must match a verification hook in the underlying package — for npm, an `mcpName` property in `package.json` must equal the registry `name`. Namespace ties to a verified identity (GitHub OAuth/device-code flow, or DNS/HTTP domain challenge), so only the legitimate owner of that GitHub account or domain can publish under it.

### Publishing workflow (official quickstart, TypeScript/npm example)
1. Publish the server package to its underlying package registry first (e.g., `npm publish`) — the registry only stores metadata, never artifacts.
2. Add a verification property to the package (`mcpName` in `package.json` for npm).
3. Install the official `mcp-publisher` CLI (prebuilt binaries or Homebrew).
4. `mcp-publisher init` scaffolds `server.json`.
5. `mcp-publisher login github` (or other method) authenticates via device-code flow.
6. `mcp-publisher publish` submits `server.json`.
7. Verify via `curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=..."`.
GitHub Actions publishing automation is documented separately (linked from the quickstart, not fetched in this pass).

### Relationship to subregistries / other registries
The official model is an explicit **ecosystem**, not one monolithic directory:
- **Package registries** (npm, PyPI, Docker Hub, etc.) hold code/binaries; the MCP Registry only holds metadata pointing at them.
- **Downstream aggregators/marketplaces** are the primary intended API consumers; they pull periodically and add curation/ratings.
- **Other MCP registries ("subregistries")**: the official registry publishes an OpenAPI spec (`docs/reference/api/openapi.yaml` in the `modelcontextprotocol/registry` GitHub repo) that other registries — including private/enterprise ones — can implement for a standardized interface. The official codebase is explicitly not meant for self-hosting with support.
- **GitHub MCP Registry**: per WebSearch snippets only (github.blog, devopsdigest.com — NOT independently fetched this pass), GitHub built its own MCP registry with Anthropic and "the MCP Steering Committee," where servers self-published to an "OSS MCP Community Registry" automatically appear in the GitHub MCP Registry. Consistent with the official "downstream aggregator" model above, but exact mechanics are **unverified** pending a primary-source fetch.

## 3. Anthropic Guidance for Tool/Server Design

### (a) "Writing tools for agents" — https://www.anthropic.com/engineering/writing-tools-for-agents
Published 2025-09-11 (per fetch, 2026-08-26).

Concrete recommendations and numbers:
- **Namespacing**: use prefix- or suffix-based namespacing to group related tools (e.g. `asana_search`, `asana_projects_search`); the post reports the choice between prefix- vs suffix-based namespacing had "non-trivial effects on tool-use evaluations" (exact percentage not given in the fetched summary).
- **Consolidation**: build higher-level workflow tools instead of thin 1:1 API wrappers — e.g. one `schedule_event` instead of separate list/create tools, or `get_customer_context` that compiles everything at once, rather than forcing the agent to orchestrate many small calls.
- **Configurable response verbosity**: tools should support a `"concise"` vs `"detailed"` response mode. Cited example: a Slack thread response was **206 tokens in detailed form vs 72 tokens in concise form** (~65% reduction).
- **Token efficiency defaults**: pagination, filtering, and truncation with sensible defaults; Claude Code caps tool responses at **25,000 tokens by default**; steer agents toward targeted searches over broad ones.
- **Error messages**: return actionable, specific guidance (not opaque codes) so the agent can self-correct parameter mistakes.
- **Tool descriptions matter a lot**: "small refinements to tool descriptions can yield dramatic improvements" — the post cites Claude Sonnet 3.5 reaching state-of-the-art on SWE-bench Verified partly via precise tool-description refinement (exact delta not specified in fetched content).
- **Semantic identifiers over technical ones**: returning human-readable/semantic identifiers instead of raw UUIDs "significantly improves Claude's precision in retrieval tasks" (no percentage given).

### (b) "Code execution with MCP" — https://www.anthropic.com/engineering/code-execution-with-mcp
Published 2025-11-04 (per fetch, 2026-08-26).

Problem identified with traditional MCP tool-calling at scale:
1. **Tool definition overload**: loading every connected server's tool definitions upfront can burn "hundreds of thousands of tokens before reading a request" when thousands of tools are connected.
2. **Intermediate result duplication**: chained tool calls pass full intermediate results through model context multiple times. Cited example: downloading a meeting transcript and attaching it to Salesforce makes the transcript flow through context twice, potentially adding "an additional 50,000 tokens" for a 2-hour meeting.

Proposed solution: present MCP servers as **code APIs in a filesystem structure** so agents can (1) load only the tool definitions actually needed, on demand; (2) filter/transform data inside a code-execution sandbox before any of it re-enters model context; (3) express multi-step orchestration as normal code (loops, conditionals) instead of chained tool-call/tool-result round trips.

**Quantified result** (the one specific number in the post): a workflow's token usage dropped from **150,000 tokens to 2,000 tokens — a 98.7% reduction** in cost/tokens for that example.

Trade-off named explicitly: this requires a "secure execution environment with appropriate sandboxing, resource limits, and monitoring" — i.e., code execution moves complexity from prompt/context design into sandboxing infrastructure.

### (c) Tool Search / programmatic tool calling (docs.claude.com / platform.claude.com)
Source: https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool (fetched 2026-08-26).

**The problem, quantified**: a typical multi-server setup (GitHub, Slack, Sentry, Grafana, Splunk) can consume **~55k tokens in tool definitions before Claude does any work**. Separately, tool-selection accuracy "degrades once you exceed 30–50 available tools" regardless of token budget.

**The fix — tool search tool**: Claude searches a catalog (tool names, descriptions, argument names/descriptions) and loads only what it needs on demand, instead of all definitions being resident in context upfront. Anthropic states this **"typically reduces [context consumption] by over 85 percent,"** loading only the ~3-5 tools needed per request, and that selection accuracy "stays high even across thousands of tools" because only a focused set loads at a time.

Mechanics (current API, tool versions dated `20251119`, i.e. released ~2025-11-19):
- Two variants: `tool_search_tool_regex_20251119` (Claude writes Python `re.search()` patterns, case-insensitive, max 200 chars) and `tool_search_tool_bm25_20251119` (natural-language queries, max 500 chars).
- Tools not needed immediately are marked `defer_loading: true` in the `tools` array (still sent in full on every request — the server needs them to run search/expansion) — but excluded from the system-prompt prefix, so **prompt caching is preserved**.
- Search returns `tool_reference` blocks (default 5 results, caller/model can set `limit` 1–10,000) which the API auto-expands into full tool definitions.
- At least one tool (normally the search tool itself) must stay non-deferred; max **10,000 deferred tools per request**.
- Supported on: Claude Opus 5, Sonnet 4.6/4.5, Haiku 4.5, Opus 4.5/4.6/4.7/4.8, and the model referred to in the docs as "Claude Fable 5"/"Claude Mythos 5" (naming as shown in the live docs table — note some of these look like internal/codenamed model entries in the doc; treat exact model lineup as of-fetch-date snapshot, not a stable list). Opus 4.1 and earlier do NOT support it.
- Guidance on when to use it: 10+ tools, tool definitions >10k tokens, accuracy dropping as toolset grows, aggregating 200+ tools across multiple MCP servers, or a growing tool library over time. Not recommended below 10 tools / <100 tokens of definitions / when every tool is used every request.
- Not separately metered/billed — tool defs loaded via search simply count as normal input tokens.
- MCP-specific integration: when tools come from MCP servers via the MCP connector, `defer_loading` is set once on the `mcp_toolset` entry's `default_config` (or per-tool in `configs`) rather than per individual tool definition.

**Programmatic tool calling (PTC)**: found via search (https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling, https://platform.claude.com/docs/en/agent-sdk/tool-search — not independently fetched this pass, so treat mechanics as **unverified** beyond this summary) — described as trading "a small fixed overhead (container startup, script generation) for large savings on tool-result tokens and model round-trips," i.e. Claude writes code that orchestrates multiple tool calls inside an execution environment rather than issuing one tool call per turn. This is the same architectural idea as the "code execution with MCP" post (3b) but exposed as a first-class Claude API feature. Positioned alongside tool search, prompt caching, and context editing as the four main context-management levers offered to developers.

### (d) Agent Skills — SKILL.md spec (agentskills.io) and composition with MCP
Source: https://agentskills.io/specification (fetched 2026-08-26); https://github.com/anthropics/skills (the spec itself now lives externally at agentskills.io — the Anthropic repo's `spec/agent-skills-spec.md` is just a pointer to https://agentskills.io/specification, confirming Agent Skills is now governed as an **open, cross-vendor spec** rather than an Anthropic-only format).

**Directory structure**: a skill is a directory with a required `SKILL.md` plus optional `scripts/` (executable code), `references/` (docs loaded on demand), `assets/` (templates/images/data files), and arbitrary other files.

**SKILL.md = YAML frontmatter + Markdown body.** Frontmatter fields, with exact constraints:
- `name` (**required**): 1–64 chars; lowercase unicode alphanumeric + hyphens only; can't start/end with hyphen; **no consecutive hyphens**; must match the parent directory name.
- `description` (**required**): 1–1024 chars, non-empty; must describe both what the skill does AND when to use it (spec explicitly contrasts a "good" keyword-rich example against a "poor" one-line example).
- `license` (optional): license name or pointer to a bundled license file.
- `compatibility` (optional): 1–500 chars; environment requirements (target product, system packages, network access, e.g. "Requires Python 3.14+ and uv"); spec notes "most skills do not need" this field.
- `metadata` (optional): free-form string-to-string map for client-specific extensions; keys recommended to be namespaced to avoid collisions.
- `allowed-tools` (optional, **explicitly marked Experimental**): space-separated string of pre-approved tools the skill may invoke, e.g. `Bash(git:*) Bash(jq:*) Read`; spec warns support "may vary between agent implementations."

**Progressive disclosure — three explicit stages**:
1. **Metadata (~100 tokens)**: only `name` + `description` loaded at startup, for ALL installed skills.
2. **Instructions (<5,000 tokens recommended)**: full `SKILL.md` body loads only once a skill is activated/matched to the task.
3. **Resources (loaded as needed)**: files under `scripts/`, `references/`, `assets/` load only when the activated skill's instructions actually reference them.

Spec recommends keeping `SKILL.md` **under 500 lines**, pushing detail into referenced files, and keeping file references only one level deep from `SKILL.md` (avoid nested reference chains). A reference validator CLI (`skills-ref validate ./my-skill`) exists at github.com/agentskills/agentskills.

**Composition with MCP**: the fetched agentskills.io spec page itself does not describe MCP composition mechanics directly (I did not find an explicit "skills + MCP" integration section in the page content retrieved). However, the official MCP spec's own site documents an explicit extension for this — **"Skills over MCP"** is listed as a named MCP extension ("Rich, structured instructions for agent workflows, discovered and consumed through MCP") alongside Tasks and MCP Apps in the specification overview fetched in Topic 1 (https://modelcontextprotocol.io/specification/, and referenced at `/community/working-groups/skills-over-mcp`). This indicates Agent Skills and MCP are being formally bridged via an MCP-side working group/extension rather than Skills being merely an Anthropic-product-only feature — exact mechanics of that bridge are **unverified** (page not fetched this pass).

## 4. SDK State

Sources: WebSearch (2026), https://pypi.org/project/mcp/ (fetched 2026-08-26), https://py.sdk.modelcontextprotocol.io/whats-new/ (fetched 2026-08-26), https://gofastmcp.com/getting-started/welcome (fetched 2026-08-26), https://pypi.org/project/fastmcp/ (fetched 2026-08-26), WebSearch for TypeScript SDK (2026, snippet-level).

### Official Python SDK (`mcp` on PyPI, modelcontextprotocol/python-sdk)
**Major finding — the official SDK jumped to a v2.x line to match the 2026-07-28 spec redesign.** Per PyPI (fetched 2026-08-26): latest version **2.1.1**, released **2026-08-25** (i.e., literally the day before this research was conducted). Per WebSearch snippets (unverified beyond snippet level): 2.0.0 shipped 2026-07-28 (same day as the spec revision), 2.1.0 shipped 2026-08-24.

Per the official "what's new in v2" page (py.sdk.modelcontextprotocol.io/whats-new/, fetched 2026-08-26):
- **v2 implements the 2026-07-28 spec while remaining backward compatible with 2025-11-25 clients** — a single deployment can serve both protocol eras simultaneously (consistent with the new `server/discover` negotiation mechanism from Topic 1).
- **"FastMCP is now MCPServer"** — this is a significant rename inside the *official SDK*: the high-level server class that used to be imported as `from mcp.server.fastmcp import FastMCP` is now `from mcp.server import MCPServer`, with the old import path removed entirely (not just deprecated). The decorator-based API this class exposes is the same lineage the standalone FastMCP project originated.
- Client architecture consolidated: v1's three-layer setup (transport context manager + `ClientSession` + manual initialization) collapses into a single `Client` object used as an async context manager, matching statelessness.
- Low-level server layer rebuilt: handlers now use a consistent `async (ctx, params) -> result` signature instead of decorator registration; parameter validation moved off strict jsonschema enforcement.
- All Python-side field names converted to snake_case (`result.is_error`, `tool.input_schema`, `listing.next_cursor`); wire protocol itself stays camelCase per spec.
- Server-initiated push calls (elicitation/sampling/roots) are gone from the SDK's API surface, replaced by `InputRequiredResult`-based flows matching the spec's new MRTR pattern (Topic 1).
- **v1.x gets indefinite maintenance-level support**, with docs preserved at `/v1/`; official guidance for existing dependents is to pin `mcp>=1.28,<2` until migrated, since a bare `pip install mcp` now resolves to the 2.x line.
- Official production recommendation as of the fetched page: install v2 for new deployments.

### Standalone FastMCP (jlowin/fastmcp, "gofastmcp.com")
**There is a 3.x, and it is the current stable line** — confirmed via PyPI (fetched 2026-08-26): latest stable **3.4.7**, released **2026-08-10**. Pre-release **4.0.0b3** beta versions also exist on PyPI, meaning a 4.0 is already in beta as of this research date.

Per gofastmcp.com (fetched 2026-08-26): the standalone project describes itself as "the standard framework for working with MCP," handling "schema generation, validation, transport, authentication, and protocol compatibility." It states "FastMCP 1.0 was incorporated into the official MCP Python SDK in 2024," and claims (self-reported, **unverified against independent data**) it is "downloaded a million times a day" and that "some version of FastMCP powers 70% of MCP servers across all languages." The fetched welcome page did not state an explicit recommendation of itself over the official SDK for production, or vice versa — treat the "which one for production" question as **not directly answered by either official source fetched**; the practical distinction found is: official SDK v2's `MCPServer` class is the low-level-SDK-bundled, spec-tracking option with guaranteed same-day alignment to protocol revisions (v2.0.0 shipped literally on 2026-07-28), while standalone FastMCP 3.x/4.0-beta is the independently-versioned, higher-level framework layer with a much larger ecosystem/plugin surface and its own release cadence (3.4.7 on 2026-08-10, i.e. it had not yet caught up to shipping day-of support for 2026-07-28 at that point, though it may have since — unverified without a changelog fetch). Architecture projects should pin explicitly and not assume "FastMCP" unqualified means the same thing in both contexts, given the official SDK reused and then dropped that name internally.

### TypeScript SDK (`@modelcontextprotocol/sdk` on npm, modelcontextprotocol/typescript-sdk)
Source: WebSearch snippets only (npmjs.com, github.com/modelcontextprotocol/typescript-sdk, ts.sdk.modelcontextprotocol.io/v2/ — **none independently fetched this pass**, treat as lower-confidence than the Python SDK findings above).
- Search snippet claims npm's published `@modelcontextprotocol/sdk` was at **1.30.0** as of roughly a month before this research (i.e., approx. late July 2026) — this looks stale relative to the v2 status below and **could not be confirmed live**; flagged in Unresolved.
- A **v2 of the TypeScript SDK**, tracking the 2026-07-28 spec, was in beta per search results, with stable release "expected to land alongside the spec on 2026-07-28." Given today is 2026-08-26 (a month past that target), whether v2 has actually reached stable/latest-on-npm by now is **unverified** — the WebSearch snippet describing 1.30.0 as latest may simply be out of date relative to a v2 stable release that shipped since. Needs direct npm/GitHub releases fetch to confirm, not done this pass due to budget.
- Per search snippets: TypeScript SDK v2 defaults to speaking the pre-2026-07-28 (2025-era) protocol; opting a server/client into the 2026-07-28 wire format is an explicit flag, and one server instance can reportedly serve both 2026-07-28 and 2025-era clients side by side (consistent with the Python SDK's dual-era support described above, and with the protocol's own `server/discover` negotiation mechanism). Also reportedly implements stateless core, MRTR, and `Mcp-Method`/`Mcp-Name` header-based routing/caching — all consistent with the 2026-07-28 spec changes documented in Topic 1.

### Other language SDKs
Not independently researched this pass due to budget constraints — **unverified**. The MCP roadmap (Topic 1) references an "SDK tiering system" (SEP-1730, established 2025-11-25) and a "Tier 1 SDK" generated-artifacts experiment planned for the current roadmap period, implying an official multi-language tiering exists, but which specific languages (Java, C#/.NET, Go, Kotlin, Ruby, Swift, PHP, Rust, etc.) currently hold "Tier 1" (first-class/officially maintained) status was not verified in this research pass. The tool-search-tool docs page (Topic 3c) did show live C#, Go, Java, PHP, Ruby code samples in Anthropic's own Claude API docs, which at minimum confirms Anthropic's own API SDKs span those languages — but that is the Claude API SDK family, not the MCP protocol SDK family, and should not be conflated. Flagged in Unresolved.

## 5. Client Feature Support Matrix

Sources: https://modelcontextprotocol.io/clients (fetched 2026-08-26 — redirected to a generic "what is MCP" page, no table), https://modelcontextprotocol.io/extensions/client-matrix (fetched 2026-08-26, the actual matrix page, reached via a link discovered on the MCP Apps page).

**Important scoping finding**: the matrix that actually exists at modelcontextprotocol.io tracks support for the three **official extensions** (MCP Apps, OAuth Client Credentials, Enterprise-Managed Authorization) — it is NOT a matrix of core primitives (tools/resources/prompts/elicitation/sampling/roots) by client. The `/clients` URL named in the task brief did not return such a table when fetched; it returned generic protocol-overview marketing copy. A core-primitive-by-client matrix was not located within budget. This itself is a useful finding: **do not assume such a matrix is maintained/published**; core primitive support (tools/resources/prompts) is close to universal across compliant clients by protocol design, while the *optional* features are where divergence actually shows up, which may be why the community-maintained matrix tracks extensions instead.

Extension support matrix (community-maintained per the page's own note; "submit a pull request" to correct — treat as directionally accurate, not authoritative for any single client at any single moment):

| Client | MCP Apps (`io.modelcontextprotocol/ui`) | OAuth Client Credentials | Enterprise-Managed Auth |
|---|---|---|---|
| Claude (web, claude.ai) | Yes | — | — |
| Claude Desktop | Yes | — | — |
| VS Code GitHub Copilot | Yes | — | — |
| Microsoft 365 Copilot | Yes | — | — |
| Goose | Yes | — | — |
| Postman | Yes | — | — |
| MCPJam | Yes | — | — |
| ChatGPT | Yes | — | — |
| Cursor | Yes | — | — |
| Archestra.AI | Yes | — | Yes |
| PostHog Code | Yes | — | — |

("—" = no checkmark shown on the live page, i.e. not confirmed supported, not necessarily confirmed absent.)

Notable: **every client listed shows MCP Apps support**, including ChatGPT and Cursor — meaning the interactive-UI-in-tool-results extension (Topic 6) already has broad, not narrow, adoption across major hosts as of this fetch. No client shows OAuth Client Credentials support on this page. Only Archestra.AI shows Enterprise-Managed Authorization. Claude Code was not a row on this particular table (only "Claude (web)" and "Claude Desktop" are broken out); its extension support is therefore **unverified** from this page specifically. Gemini was not listed on this table at all — **unverified** whether that means no support, or simply that the community table hasn't been updated for it.

On core primitives specifically (tools/resources/prompts/elicitation/sampling/roots) — **not verified via a live matrix this pass**. What IS verified from Topic 1: as of the 2026-07-28 spec, **Roots, Sampling, and Logging are formally deprecated protocol-wide** (SEP-2577), and Elicitation's server-initiated push mechanism was folded into the general MRTR pattern. This means a framework built against early-2026 assumptions (treating elicitation/sampling/roots as the three client-side features to check for) is now checking against a moving target: two of those three are being phased out at the spec level regardless of any individual client's support, and the architecturally current question is closer to "does this client support MRTR / the 2026-07-28 stateless wire format" than "does this client support sampling." This is flagged prominently in the summary.

## 6. MCP Apps / UI Extension

Source: https://modelcontextprotocol.io/extensions/apps/overview (fetched 2026-08-26); cross-checked against the extension support matrix above (also fetched 2026-08-26).

**Status: shipped as a formal, named extension — not merely a proposal.** MCP Apps is documented as "an extension to the core MCP specification" with its own spec repository (`github.com/modelcontextprotocol/ext-apps`), its own versioned spec document (`specification/2026-01-26/apps.mdx` in that repo — note this is dated 2026-01-26, i.e. it shipped as an extension spec *before* the 2026-07-28 core protocol revision), a capability identifier (`io.modelcontextprotocol/ui`) used in the standard extension-negotiation mechanism (via `extensions` field in `ClientCapabilities`/`ServerCapabilities`, itself added in the 2026-07-28 core spec per Topic 1), and a documentation site at apps.extensions.modelcontextprotocol.io. It is explicitly listed alongside Tasks and "Skills over MCP" as one of the specification's "Notable extensions" on the main specification page (Topic 1).

**What it enables**: tools declare a `_meta.ui.resourceUri` pointing to a `ui://` resource; the host preloads/fetches that resource (an HTML page, often bundled with its own JS/CSS) and renders it in a **sandboxed iframe** inside the conversation. The app and host communicate over `postMessage` using an MCP-like JSON-RPC dialect (some methods shared with core MCP, e.g. `tools/call`; most new, prefixed `ui/`, e.g. `ui/initialize`). Apps can request tool calls back through the host, receive pushed data/context updates, and request extra permissions (microphone, camera) or relaxed CSP for external origins — all under host-controlled sandboxing (no DOM/cookie/localStorage access to the parent page, no parent navigation).

**Client support**: per the extension matrix (Topic 5 above, fetched same day), MCP Apps is checked as supported by Claude (web), Claude Desktop, VS Code GitHub Copilot, Microsoft 365 Copilot, Goose, Postman, MCPJam, ChatGPT, Cursor, Archestra.AI, and PostHog Code — i.e., broad support across both Anthropic and non-Anthropic hosts already.

**Relationship to "MCP-UI"**: the docs distinguish the official spec extension from a separate community project — `@mcp-ui/client` (React components, at github.com/MCP-UI-Org/mcp-ui, docs at mcpui.dev) is named as one of two integration paths a client author can use (the other being Anthropic's own `App`/`AppBridge` SDK, `@modelcontextprotocol/ext-apps`). This suggests "MCP-UI" (community, org `MCP-UI-Org`) and "MCP Apps" (official spec extension) are related-but-distinct: MCP-UI reads as a client-side rendering library that implements/consumes the official MCP Apps protocol, not a competing spec. This relationship is stated by the official docs but was not independently cross-verified against the MCP-UI project's own site — **unverified in detail**.

Framework support: official starter templates exist for React, Vue, Svelte, Preact, Solid, and vanilla JS (github.com/modelcontextprotocol/ext-apps/tree/main/examples), plus a substantial example gallery (3D/visualization, data exploration, business apps, media viewers, utilities) — indicating this is past the "toy proposal" stage and into real reference-implementation breadth.

## 7. Governance

Sources: governance/process items surfaced directly in the 2025-11-25 and 2026-07-28 spec changelogs, and the roadmap page (all fetched under Topic 1, 2026-08-26). No additional dedicated governance-page fetch was performed this pass (budget).

MCP governance was **formalized starting with the 2025-11-25 revision**: a governance structure (SEP-932), community communication practices (SEP-994), and **Working Groups / Interest Groups** (SEP-1302) were all adopted in that revision, alongside an **SDK tiering system** (SEP-1730) defining maintenance/feature-support commitments per language SDK. The **Specification Enhancement Proposal (SEP)** process is the mechanism for all protocol changes — visible throughout both changelogs, where essentially every substantive change cites a specific SEP number and PR. As of 2026-07-28, the SEP workflow was further formalized as **PR-based, with markdown files in a `seps/` directory and PR-derived numbering** (SEP-1850), plus a formal **feature lifecycle and deprecation policy** (Active/Deprecated/Removed states, minimum 12-month deprecation window, SEP-2596).

In practice (per the roadmap page, "last updated 2026-08-22"), governance now runs through named **Core Maintainers** owning specific roadmap priority areas (e.g., Caitie McCaffrey, Clare Liguori, and Peter Alexander on Agentic Messaging Primitives; Kurtis Van Gent and Nick Cooper on HTTP-Native Transport; Paul Carleton and Den Delimarsky on Agent Identity/Security; Den Delimarsky and David Soria Parra on SDK Developer Experience), each reachable via Discord, with active and forming Working Groups (Triggers & Events, Agents, Transports, Agent Identity [forming], Core Primitives [forming], File Uploads, SDK) driving specific deliverables. SEPs aligned with a named roadmap priority area and backed by a Working Group get "expedited review"; others face "a longer queue and higher bar."

No evidence of a formal legal foundation (e.g., a Linux-Foundation-style independent foundation entity) was found or searched for directly in this pass — **unverified** either way; the governance described reads as a maintainer/steering-committee model (a "MCP Steering Committee" was referenced in one unverified WebSearch snippet in Topic 2, in the context of the GitHub MCP Registry, but its formal relationship to the Core Maintainers/Working Group structure described above was not independently confirmed).

## Unresolved

- **Registry API freeze claim**: "v0.1 API freeze" for the registry was only seen in a WebSearch snippet (not fetched from a primary source). The `/v0.1/servers` path is confirmed live via the quickstart's own curl example, but whether the registry team has formally declared a freeze is unconfirmed.
- **GitHub MCP Registry mechanics**: relationship between GitHub's MCP Registry, an "OSS MCP Community Registry," and the official registry.modelcontextprotocol.io was only seen via WebSearch snippets (github.blog, devopsdigest.com), never fetched directly. Exact auto-sync mechanics unconfirmed.
- **"Skills over MCP" bridge mechanics**: confirmed to exist as a named MCP working group/extension (referenced from the main specification page), but its actual mechanics (how a skill is discovered/served as an MCP primitive) were not fetched from `/community/working-groups/skills-over-mcp`.
- **Programmatic tool calling (PTC) full mechanics**: summarized only from a WebSearch snippet of platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling; the page itself was not fetched, so implementation details beyond "trades fixed overhead for saved round-trips/tokens" are unconfirmed.
- **TypeScript SDK current published version**: WebSearch snippets conflict/are ambiguous — one suggests npm's `@modelcontextprotocol/sdk` "latest" was 1.30.0 "a month ago" (~late July 2026), while other snippets describe a v2 targeting stable release on 2026-07-28 itself. Given today is 2026-08-26, whether v2 is now the npm "latest" tag is unconfirmed — needs a direct fetch of npmjs.com/package/@modelcontextprotocol/sdk or github.com/modelcontextprotocol/typescript-sdk/releases.
- **Standalone FastMCP's current spec-version support**: confirmed 3.4.7 stable (2026-08-10) and 4.0.0b3 beta exist, but whether either has caught up to full 2026-07-28 core-spec support (stateless core, MRTR, `server/discover`) was not verified — the fetched welcome page reflects "main branch, may describe unreleased features" per its own disclaimer, so even that wasn't a clean read of the released version's capabilities.
- **Official SDK tier list by language**: existence of an "SDK tiering system" (SEP-1730) is confirmed; which languages hold Tier 1 status today is not.
- **Core-primitive-by-client support matrix** (tools/resources/prompts/elicitation/sampling/roots, specifically, as opposed to the three official extensions): not found published anywhere located in this pass. May not exist as a maintained artifact — see Topic 5 discussion.
- **Claude Code's and Gemini's extension support**: absent as explicit rows from the fetched `/extensions/client-matrix` table (only "Claude (web)" and "Claude Desktop" appear for Anthropic products; Gemini does not appear at all). Absence from a community-maintained table is weak evidence of non-support, not confirmation.
- **Tool annotations (`readOnlyHint` etc.) current exact field list**: assumed stable since 2025-06-18 based on absence from later changelogs, but the current server/tools spec page was not fetched directly to confirm the exact annotation set as of 2026-07-28.
- **Pagination and completions spec details**: assumed unchanged since 2025-06-18 based on absence from later changelogs; not independently confirmed against the current spec pages.
- **Formal foundation/legal entity status**: not confirmed either way; "MCP Steering Committee" appeared once in an unverified snippet.
- **Budget note**: this research used 26 web fetches/searches against a 25-call budget — one over — spent deliberately on `/extensions/client-matrix` after `/clients` (the task-specified URL) returned no actual matrix, because Topic 5 was flagged as high decision-value ("determines what protocol features an ecosystem project can actually rely on"). All other topics stayed within the implicit per-topic allocation.

