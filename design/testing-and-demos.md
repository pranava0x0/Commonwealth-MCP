# Spec: Test and Demo Structure

**Plugs into:** architecture.md § 24 (repo layout), § 31 (evaluation); companion to bench.md (which owns the model-in-the-loop tiers).
**Status:** Draft for review.
**Why this exists:** The ecosystem survey produced eight named, attributed test/demo patterns (../research/README.md part 3 § 7). This spec turns the adopted ones into the repo's actual structure so the first server lands inside it, instead of test structure accreting per-author.

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
├── test_manifest_validation.py            # every manifest, every activation rule, count printed
├── fixtures/
│   └── sources/<source-id>/               # recorded by `commonwealth sources sample`
└── toolsnaps/
    └── <server>__<tool>.json              # committed tool-schema snapshots, flat
```

(Tree corrected 2026-08-28 to the built layout: manifest validation sits at the tests root, not under a `sources/` subtree, and toolsnaps are flat `server__tool.json` files rather than per-server directories. Same content, simpler paths.)

Adaptations from the surveyed patterns, with reasons:

- **PNNL's uniform five-file taxonomy** becomes four here: their `performance` file merges into `resilience` (timeout/budget assertions) until there is a measured performance problem to test — a performance suite with no baseline is ceremony. The uniformity itself is the adopted part: a new server PR without the four files fails a repo-health test that iterates the server registry (never a hand-typed server list).
- **congressMCP's known-failures discipline**, adapted: `source-quirks.md` (repo root, as built 2026-08-28 — it is reader-facing and the README links it), where every behaviour-affecting quirk names the offline test that pins it. A quirk that stops reproducing must be removed — stale exemptions are how gates rot — and because the offline tests replay recordings, only the reconciliation audit below can notice that a quirk has stopped reproducing upstream. Quirks are per-source, dated, and linked from the source manifest's `known_limitations`. The dated upstream-reconciliation audit becomes a scheduled job producing `docs/audits/upstream-<date>.md`, run before each release: replay all fixtures against live sources, diff, file drift as `SourceSchemaChanged` findings.
- **github-mcp-server's toolsnaps**: tool schemas are snapshot-committed; changing a tool means updating registration, tests, and snap in one reviewed diff; renames require a deprecation alias entry (the alias table ships in Commonwealth Core from day one, empty, so the mechanism exists before the first rename).
- **fastmcp's in-memory pattern** (or the official SDK's equivalent, per architecture.md decision 0003): the `conftest.py` client fixture wraps server objects directly; no subprocess, no network in unit/contract tiers. Snapshot assertions use `inline-snapshot`; fuzzy fields (timestamps, cache ages) use `dirty-equals`.
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

CI never depends on government uptime; live checks are scheduled and produce reviewable artifacts instead of red PRs (the rule that time and VCS drift checks stay advisory applies to upstream drift too).

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

**Shipped 2026-08-29 (GitHub issue #30), with two changes to the sketch above.** `examples/` holds four scripts — `whose_government.py`, `screen_a_parcel.py`, `what_is_covered.py`, `two_sources_disagree.py` — chosen around what the registry can now answer rather than the names guessed here; `bill_to_code.py` still waits on the legislative API. Each prints the five coverage dimensions, sources, and warnings alongside the answer.

The first change: **`--fixtures` is the default, not the flag.** A newcomer's first run should not be able to fail on a network, a firewall, or a government service being down at the wrong moment, so the recorded mode runs unless `--live` is passed. The scripts say which mode they ran in on their first line.

The second: **the offline seam moved into the package** (`commonwealth/fixtures.py`). It lived in `tests/conftest.py`, and a script someone runs should not have to import a test module to work. `conftest` now calls it, so there is one implementation rather than two that can drift.

`tests/test_examples.py` runs each script as a subprocess exactly as a reader would — imports, argument parsing, and all — because an example nobody runs rots into a wrong tutorial. It also asserts the README's table lists every script, and that no example imports from the test suite.
- The walkthrough transcript is a maintained artifact with a date, refreshed by the release process, because a stale demo transcript is anti-marketing.
- MCP Inspector configs (`examples/inspector/`) ship for each server: the survey's universal baseline, and the first thing an evaluating developer reaches for.

## 4. The structural rule underneath all of it

Every enumerating check derives its list from the registry it checks (servers from the server registry, manifests from the sources directory, tools from tool registration, fixtures from the fixtures tree) and prints the count it examined. The surveyed repos' best patterns all reduce to this; the base files' hard-won rule ("a gate that says 0 failures over 12% of the corpus is indistinguishable from one that says it over all of it") is the same lesson from the other direction.
