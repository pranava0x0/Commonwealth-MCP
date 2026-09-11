# Commonwealth Bench

The runner for `design/bench.md`. Three tiers are specified; Tier 1 lives
with the code as ordinary tests and is reported here rather than owned
here. This directory owns tiers 2 and 3.

```bash
commonwealth eval list                    # the suites, and what each covers
commonwealth eval validate                # load every task; report trap coverage
commonwealth eval run tier2               # oracle run over the default toolset
commonwealth eval run tier2 --profile all # the same suite over every tool
```

## Two modes, and the difference matters

**Oracle** (the default) executes each task's own `expected` call against
the fixture-backed server and scores the envelope assertions. No model,
no cost, runnable in CI.

It does not measure a model. It measures whether a task's ground truth
is achievable at all — which is what stops a trap passing vacuously
against a server that cannot produce the answer the trap asserts. A task
that scores `coverage_honesty` while asserting no coverage value, no
warning and no next_action fails as unfallible rather than scoring a
free pass.

**Model** is the Tier-2 measurement proper: give a model the question and
the toolset, score what it picked. This is the one part of the bench that
costs money (`design/bench.md` § 6), and no client is wired — `--model`
says so rather than pretending. Wiring one is what remains of GitHub
issue #28.

## Layout

```text
evals/
  tasks/<suite>/*.yaml      Tier-2 tasks, the public set
  skills/<skill>/*.yaml     Tier-3 walks, one directory per shipped skill
  baselines/*.json          results keyed by (suite, model, toolset)
  hidden/                   the maintainer-held half of the split (§ 3)
```

Every task is the `design/bench.md` § 2 format. `fixtures:` names
directories under `tests/fixtures/sources/`; nothing here reaches the
network, because a bench that did would score whether a government host
was slow that morning.

## The public/hidden split

`design/bench.md` § 3: the repo carries task YAML, fixtures, scorers and
baselines. The maintainer holds mutated variants — different parcels,
dates and aliases — and runs them before releases, so a published score
measures the system rather than memorised fixtures.

`hidden/` mirrors this layout and is not committed. The runner loads it
when it is there and records which splits a run covered, so the split is
wired from the first published number. Retrofitting one later
re-litigates every number published before it.

## Baselines

`evals/baselines/` holds one result per (suite, model, toolset). CI
compares against the baseline and fails on regression past a stated
threshold:

```bash
commonwealth eval run tier2 --baseline evals/baselines/tier2-oracle-default.json
```

An improvement warns rather than updating the file. A baseline that
updated itself on a good day would ratchet quietly and stop being a
baseline; updating one is a reviewed change like any other.
