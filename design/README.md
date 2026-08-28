# Design

Per-feature specs: what each feature contracts to do, in its current adopted shape. One file per feature, because the code cites them by name and each is written to be pulled into context on its own.

The decisions these depend on moved to [DECISIONS.md](../DECISIONS.md) in 2026-08-28's consolidation — fifteen files of 25-47 lines each that were only ever read as a set, and whose status was correct only in the index table they were separated from. A spec's header still names the decisions it depends on; those now resolve to sections of that file.

## Specs

Each spec is self-contained, written to be pulled into context alone: it names the [ARCHITECTURE.md](../ARCHITECTURE.md) sections it expands (`Plugs into:`), carries its own evidence pointers, and ends with testing hooks. ARCHITECTURE.md stays the map; these are the territories.

Reading order for a first pass mirrors the dependency order:

| Spec | What it fixes | Depends on decisions |
|---|---|---|
| [provenance-envelope.md](provenance-envelope.md) | The result contract every tool returns: data/provenance/coverage/warnings, token budgets, error integration | 0012 (field freeze at Gate A) |
| [jurisdiction-resolution.md](jurisdiction-resolution.md) | The jurisdiction model, resolution tool, ambiguity behavior, the Fairfax traps | 0004 |
| [source-registry.md](source-registry.md) | Manifest schema, terms/activation gates, contribution workflow, inventory-first sequencing | 0005 |
| [adapters.md](adapters.md) | The adapter contract, initial three adapters, spatial rules, politeness | 0003 |
| [domain-servers.md](domain-servers.md) | Tool conventions and V1 contracts for registry/geo/civic | 0001, 0002, 0005 |
| [skills.md](skills.md) | Skill packaging (agentskills.io), shape, anti-patterns, eval requirement | 0007 |
| [bench.md](bench.md) | Three eval tiers, task format, traps, public/hidden split, reporting | 0002 |
| [security-and-data-handling.md](security-and-data-handling.md) | Threat model, egress policy, data classification, log minimization, governance prerequisites | 0014 |
| [explorer.md](explorer.md) | Long-tail querying boundaries and the manifest-promotion pipeline (deferred design — no V1 build per 0008 as revised) | 0008 |
| [hub-catalog.md](hub-catalog.md) | Catalog schema, capability routing and profiles (pre-Hub), external integration modes, tenancy | 0009, 0013 |
| [cli.md](cli.md) | The `commonwealth` command tree and its non-negotiables | 0015 |
| [testing-and-demos.md](testing-and-demos.md) | Test tree, quirks register, reconciliation audits, demo layout | — |
| [docs-practices.md](docs-practices.md) | Doc structure, register gates, agent-facing strings as docs | — |

Conventions all specs follow: `Status: Draft for review` until the architect accepts; a spec whose decision dependency is unchosen cannot graduate; edits that change a contract bump the spec's own status line and note the date.

## Changelog

| Date | What changed |
|---|---|
| 2026-08-26 | Specs and decision records written together in this folder. |
| 2026-08-28 | The fifteen decision records moved to [DECISIONS.md](../DECISIONS.md). The specs stayed as files: source code cites them by filename in 34 places, and each is meant to be read alone. |
