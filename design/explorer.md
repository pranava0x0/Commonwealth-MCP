# Spec: Commonwealth Explorer

**Plugs into:** Design Spec § 13 (Commonwealth Explorer), § 5 Option D
**Status:** Deferred design (revised 2026-08-26). Per DECISIONS.md 0008 as revised after the architecture review, no Explorer tool surface ships in V1 — the contributor CLI (`sources probe/sample`, `tools call`) covers exploration for the people actually doing it in year one. This spec stands as the design for the Phase-4 revisit; nothing in it authorizes earlier work.
**Why this exists:** Virginia's long tail (hundreds of locality GIS servers, one-off open-data portals, odd agency APIs) will never all be normalized into semantic tools, and should not be. Explorer is the controlled path for querying a *registered but not yet normalized* source, and the pipeline that turns repeated exploration into manifests. Cloudflare's Code Mode proved the token economics; the protocol's own direction (tool search shipped, server-side progressive discovery on the roadmap) validates dynamic surfaces (RESEARCH.md part 1 § 1, § 4).

---

## 1. Boundaries that make Explorer safe to exist

1. **Registry-bound.** Explorer reaches only sources with a manifest, including `proposed` ones, provided `automation_status` permits. It is never a generic HTTP client; `do_not_automate` and `unknown` sources are invisible to it. The community security consensus treats arbitrary-outbound as the cardinal sin (RESEARCH.md part 4 § 4); Explorer's entire design answer is the allowlist it inherits from the registry.
2. **Read-only by construction.** Adapter methods available to Explorer are the read set (`discover/describe/query/paginate`); no adapter write paths exist in V1 anywhere, so Explorer cannot reach one.
3. **Enveloped like everything else.** Explorer results carry the standard envelope with `authority_level` from the manifest and a standing `warnings` entry: `unnormalized_source` ("field semantics not yet reviewed; treat as raw").
4. **Separately activated.** Explorer is its own toolset/profile, off by default, so ordinary civic users never see it and its token cost is opt-in.

## 2. Tools

```text
explorer.search_sources(query, jurisdiction?)     # over the registry, incl. proposed
explorer.inspect(source_id)                        # adapter describe(): layers, fields, samples
explorer.query(source_id, query)                   # declarative query object, adapter-validated
explorer.propose_manifest(source_id, mapping)      # emits a draft manifest + fixture, § 4
```

`explorer.query`'s `query` argument is a declarative object (filters, fields, geometry, limit, offset), validated against the adapter's parameter schema, translated by the adapter. It is not SQL, not code, and not vendor query syntax, though adapters may pass vendor syntax through *validated* sub-fields where the platform's own query language is the only expressive option (ArcGIS `where` clauses: allowed grammar subset, length-capped, no functions beyond a reviewed list).

## 3. Execution model: the decision that gates this spec

Three candidate models, fleshed out in DECISIONS.md 0008: (A) declarative query builder only (ship first), (B) sandboxed code execution against adapter clients (Cloudflare-style; big power, big surface), (C) none in V1 (fold exploration into the CLI for developers only). The default recommendation is A for V1 with B revisited at Phase 4 behind Gate B, but the record presents all three with their evidence.

## 4. The promotion pipeline is the point

Explorer exists to feed the registry. Mechanics:

- Every `explorer.query` logs (source_id, capability-shaped intent, fields touched) to the observability stream.
- `commonwealth sources candidates` aggregates those logs: sources queried N+ times across M+ sessions surface as normalization candidates with their most-used fields, which is exactly the field-mapping draft a contributor needs.
- `explorer.propose_manifest` turns a successful exploration session into a draft manifest plus recorded fixture; the contribution workflow (design/source-registry.md § 4) takes it from there. Design-spec § 13.2's promotion ladder, made operational.

## 5. Evaluation

Bench tasks: use Explorer to answer a question against a fixture-backed unnormalized source and produce a candidate manifest (design-spec § 32 task 10); an injection trap inside an unnormalized source's field values; a refusal check (Explorer asked to reach an unregistered URL says why it cannot, naming the registry as the path).
