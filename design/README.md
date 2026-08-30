# Design

Everything about how Commonwealth-MCP works and why.

Start with **[architecture.md](architecture.md)**. It has two parts: how
the system is put together (§ 1–39), and one record per architectural
choice with the options that lost still written out (decisions 0001–0015).

The other files here are per-feature contracts. Each one is written to be
read on its own, and the source code cites them by filename, so a comment
in `core/envelope.py` pointing at `provenance-envelope.md § 2` resolves to
something specific.

## The specs

Roughly in dependency order, which is also a reasonable reading order:

| Spec | What it settles | Decisions it rests on |
|---|---|---|
| [provenance-envelope.md](provenance-envelope.md) | What every tool result contains: data, provenance, coverage, warnings, token budgets, errors | 0012 |
| [jurisdiction-resolution.md](jurisdiction-resolution.md) | The jurisdiction model, how a place is resolved, what happens when a name is ambiguous, and the Virginia traps | 0004 |
| [source-registry.md](source-registry.md) | The manifest format, the terms and activation gates, and how a new source gets added | 0005 |
| [adapters.md](adapters.md) | The adapter contract, the first three adapters, spatial rules, and request politeness | 0003 |
| [domain-servers.md](domain-servers.md) | Tool naming and behaviour for the registry, geo, and civic packages | 0001, 0002, 0005 |
| [skills.md](skills.md) | How a skill is packaged, what shape it takes, and what it must not do | 0007 |
| [bench.md](bench.md) | Three evaluation tiers, the task format, the traps, and how results are reported | 0002 |
| [security-and-data-handling.md](security-and-data-handling.md) | Threat model, egress policy, data classification, and what logs may keep | 0014 |
| [cli.md](cli.md) | The `commonwealth` command tree | 0015 |
| [testing-and-demos.md](testing-and-demos.md) | Test layout, the quirks register, drift audits, and demos | — |
| [hub-catalog.md](hub-catalog.md) | Catalog schema, capability routing, profiles, and tenancy. Mostly ahead of what is built | 0009, 0013 |
| [explorer.md](explorer.md) | Querying the long tail, and how an ad-hoc query becomes a registered source. Deferred, not built | 0008 |
| [docs-practices.md](docs-practices.md) | How the docs are structured and what the writing checker enforces | — |

Two more files sit alongside them:

- **[source-quirks.md](source-quirks.md)** — things real government data
  does that its schema does not predict. Every entry names how it was
  found, when, and what the code does about it.
- **[architecture.md](architecture.md)** — the map the specs expand.

## Conventions

A spec carries `Status: Draft for review` until the architect accepts it.
A spec cannot graduate while a decision it depends on is still open. Any
edit that changes a contract updates the spec's status line with the date.

## Changelog

| Date | What changed |
|---|---|
| 2026-08-26 | Specs and decision records written together in this folder. |
| 2026-08-28 | The fifteen decision records merged into one file. They were only ever read as a set, and each one's status was correct only in the index table it had been separated from. |
| 2026-08-28 | Plan-vs-built review. Specs that described unbuilt things in the present tense got dated annotations saying so. Contract-level disagreements between spec and code were filed as issues rather than edited away. |
| 2026-08-29 | The architecture and the decisions merged into `architecture.md` and moved into this folder, next to the specs that expand them. `KNOWN_SOURCE_QUIRKS.md` became `source-quirks.md`. The backlog and the issues log moved to GitHub issues. |
