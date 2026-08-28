# Spec: Test and Demo Structure

**Plugs into:** Design Spec § 24 (repo layout), § 31 (evaluation); companion to design/bench.md (which owns the model-in-the-loop tiers).
**Status:** Draft for review.
**Why this exists:** The ecosystem survey produced eight named, attributed test/demo patterns (RESEARCH.md part 3 § 7). This spec turns the adopted ones into the repo's actual structure so the first server lands inside it, instead of test structure accreting per-author.

---

## 1. Test tree

```text
tests/
├── conftest.py                  # in-memory client fixture, fixture loaders
├── core/                        # envelope, jurisdiction, identity, selection units
├── adapters/
│   └── test_<adapter>_{unit,contract}.py
├── servers/
│   └── <server>/
│       ├── test_<server>_unit.py          # tool logic against fixtures
│       ├── test_<server>_contract.py      # envelope + schema + ordering + token budget
│       ├── test_<server>_resilience.py    # outage/timeout/schema-drift behavior
│       └── test_<server>_security.py      # terms gates, no-arbitrary-outbound, injection handling
├── sources/
│   └── test_manifest_validation.py        # every manifest, every activation rule, count printed
├── fixtures/
│   └── sources/<source-id>/<capability>/  # recorded by `commonwealth source sample`
└── toolsnaps/
    └── <server>/<tool>.json               # committed tool-schema snapshots
```

Adaptations from the surveyed patterns, with reasons:

- **PNNL's uniform five-file taxonomy** becomes four here: their `performance` file merges into `resilience` (timeout/budget assertions) until there is a measured performance problem to test — a performance suite with no baseline is ceremony. The uniformity itself is the adopted part: a new server PR without the four files fails a repo-health test that iterates the server registry (never a hand-typed server list).
- **congressMCP's known-failures discipline**, adapted: `tests/KNOWN_SOURCE_QUIRKS.md` + a test asserting the quirk register matches reality (a quirk that stops reproducing must be removed — stale exemptions are how gates rot). Quirks are per-source, dated, and linked from the source manifest's `known_limitations`. The dated upstream-reconciliation audit becomes a scheduled job producing `docs/audits/upstream-<date>.md`, run before each release: replay all fixtures against live sources, diff, file drift as `SourceSchemaChanged` findings.
- **github-mcp-server's toolsnaps**: tool schemas are snapshot-committed; changing a tool means updating registration, tests, and snap in one reviewed diff; renames require a deprecation alias entry (the alias table ships in Commonwealth Core from day one, empty, so the mechanism exists before the first rename).
- **fastmcp's in-memory pattern** (or the official SDK's equivalent, per DECISIONS.md 0003): the `conftest.py` client fixture wraps server objects directly; no subprocess, no network in unit/contract tiers. Snapshot assertions use `inline-snapshot`; fuzzy fields (timestamps, cache ages) use `dirty-equals`.
- **Recorded-fixture policy**: fixtures are recorded source responses (from `source sample`), never hand-written JSON — hand-written fixtures encode what the author believes the source returns, which is the drift this whole structure exists to catch. Fixtures carry their recording date; the reconciliation audit is what refreshes them deliberately.

## 2. What runs where

| Tier | Trigger | Network | Model |
|---|---|---|---|
| unit + contract + manifest validation | every PR | none | none |
| resilience + security | every PR | none (simulated failures) | none |
| source probes (`probe --all`) | schedule | live | none |
| reconciliation audit (fixture replay vs live) | pre-release + schedule | live | none |
| bench Tier 2 (tool selection) | release + contract-touching PRs | none | yes |
| bench Tier 3 (workflows) | release candidates | none | yes |

CI never depends on government uptime; live checks are scheduled and produce reviewable artifacts instead of red PRs (the base-files rule about time/VCS-drift checks being advisory applies to upstream drift too).

## 3. Demos

Adopted from civic-ai-tools' `examples/` pattern, adjusted to this project's CLI-first rule:

```text
examples/
├── README.md                    # what each shows, expected output, cost (all keyless)
├── zoning_lookup.py             # one parcel, envelope printed and annotated
├── locality_compare.py          # same capability, two counties, one outage simulated (fixture mode)
├── bill_to_code.py              # LIS bill → affected Code sections
└── due_diligence_walkthrough.md # transcript of the skill run with real output, dated
```

- Every script runs keyless against live sources (`python examples/zoning_lookup.py`), takes a `--fixtures` flag to run offline from the recorded fixtures, and prints the provenance block prominently — the demo's job is to sell the envelope, not just the answer.
- The walkthrough transcript is a maintained artifact with a date, refreshed by the release process, because a stale demo transcript is anti-marketing.
- MCP Inspector configs (`examples/inspector/`) ship for each server: the survey's universal baseline, and the first thing an evaluating developer reaches for.

## 4. The structural rule underneath all of it

Every enumerating check derives its list from the registry it checks (servers from the server registry, manifests from the sources directory, tools from tool registration, fixtures from the fixtures tree) and prints the count it examined. The surveyed repos' best patterns all reduce to this; the base files' hard-won rule ("a gate that says 0 failures over 12% of the corpus is indistinguishable from one that says it over all of it") is the same lesson from the other direction.
