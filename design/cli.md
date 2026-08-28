# Spec: The `commonwealth` CLI

**Plugs into:** Design Spec § 25 (CLI), § 24 (Repository Strategy)
**Status:** Draft for review.
**Why this exists:** Three audiences: developers who script (and who the CLI-vs-MCP research says will prefer a CLI for anything mechanical; RESEARCH.md part 4 § 3), contributors onboarding sources (the workflow in design/source-registry.md § 4 is CLI-shaped), and the project itself (base-files/CLAUDE.md: CLI-first so agents can self-validate; every gate the docs mention must be runnable locally). The CLI is also the demo surface: `commonwealth ask`-style flows show value before anyone configures a client.

---

## 1. Command tree (V1)

```text
commonwealth
├── doctor                      # env, install, config, per-server health, source reachability
├── serve [--servers a,b] [--profile NAME] [--transport stdio|http] [--port N]
│                               # --profile activates a capability profile; startup fails if a
│                               # required capability has no route (design/hub-catalog.md § 2)
├── configure <client> [--profile NAME] [--dry-run]
│                               # claude | claude-code | codex | vscode | cursor: writes/patches
│                               # client config; idempotent (re-running converges, never duplicates);
│                               # --dry-run prints the exact diff without writing
│
├── tools
│   ├── list [--server X] [--toolset Y]
│   └── call <tool> --args '<json>'      # direct invocation, prints the envelope; the debug loop
│
├── sources
│   ├── search <text> [--jurisdiction J] [--capability C]
│   ├── inspect <source-id>
│   ├── scaffold <adapter-type>
│   ├── validate <manifest|--all>
│   ├── probe <manifest|--all>           # live health; writes probe report
│   ├── sample <manifest>                # runs declared capabilities, records fixtures
│   ├── candidates                       # explorer-usage aggregation → normalization queue
│   └── stats                            # active/proposed/degraded counts by jurisdiction
│
├── catalog
│   ├── list | inspect <server-id> | health
│   └── export --format registry|client-config|gsa
│
├── eval
│   ├── run <suite> [--model M] [--toolset T]
│   └── report <result.json> [--against baseline]
│
└── version
```

Conventions:

- Every command exits nonzero on failure and prints the count of things it actually checked (the "0 verified = error, print the denominator" rule; a validator that saw an empty directory must say so and fail).
- `--json` on every read command; human tables are the default. Agents and CI consume `--json`; no screen-scraping our own tool.
- `tools call` prints the full envelope pretty-printed with provenance and coverage visible, because the envelope is the product and the debug loop should stare at it.
- No command name stutters the project ("commonwealth cw-sources"); no abbreviations in command names (flags may abbreviate).

## 2. Install and first-run

```bash
pipx install commonwealth-mcp   # or: uvx commonwealth-mcp
commonwealth doctor             # says what works, what is missing, what to do next
commonwealth configure claude-code
```

`doctor` is the front door and gets engineering attention accordingly: it verifies Python version, package integrity, config location, which servers start, and probes 2-3 keyless state sources, ending with a copy-pasteable next step. Ten-minute-install (design-spec acceptance criterion 1) is measured through `doctor`'s wall clock.

## 3. What the CLI is not

- Not a supported public API (DECISIONS.md 0015, Chosen: MCP-only V1): the CLI is the contributor/debug surface, and its `--json` output is a convenience, not a semver-governed contract. The core stays framework-free so a public library remains an additive promotion later.
- Not a second data plane: every `sources`/`tools` command calls the same adapter and core code paths the servers use; no CLI-only query logic to drift.
- Not an agent: no LLM calls inside the CLI in V1 (`eval run` invokes models through the eval harness, which is explicit about cost). A conversational `commonwealth ask` demo stays in `examples/`, not in the tool.
- Not privileged: anything the CLI can reach, the servers can reach; the CLI adds no bypass of terms gates or registry allowlists.
