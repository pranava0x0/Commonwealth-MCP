# Contributing

The architecture is settled and a first slice is implemented (see [README.md](README.md) for current state). [design/](design/README.md) holds the 15 architectural choices the project depends on — 14 are **Chosen** as of 2026-08-26; one (0009, hosted gateway) is deliberately **Deferred** to Phase 3. This document covers the two things people ask most: how to challenge a Chosen decision, and how to propose a new one.

## Proposing a new decision record

If you hit an architectural question this repo hasn't recorded an answer for — something the specs or the design spec assume rather than justify — open it as a new decision record, not a scattered GitHub issue thread. Follow the shape every existing record uses (see any file in [design/](design/) for the pattern):

1. **Context** — the problem, in 2-4 sentences, with a pointer to the spec section or code area it affects.
2. **Every credible option**, each with a for/against list grounded in evidence (a benchmark, a peer project's choice, a spec citation) — not just intuition. Options are never deleted once a choice is made; that's the point of the format.
3. **A recommendation**, stated plainly, with "what would change this" — the conditions that would flip it.
4. Open a PR adding the file under `design/NNNN-short-name.md` (next number in sequence) and a row in [design/README.md](design/README.md)'s table with status **Open**.

A maintainer (or the project's architect) reviews the framing before it's actionable — a record with weak options or a recommendation with no evidence behind it gets sent back for more homework, the same review anyone's own proposal would get.

## Proposing to reopen a Chosen decision

A Chosen record is not permanent, but reopening one costs more than proposing a new one — implementation may already depend on it. Before requesting a reopen:

- Read the record's **"What would change this"** section (recommendation) and its **"Choice"** section (the architect's actual reasoning, including any deviation from the recommendation). If your argument doesn't address the stated trigger conditions, it's not ready yet.
- Have new evidence, not a preference: a benchmark result, a changed upstream fact (a library shipped stable, a client added protocol support, a source's terms changed), or a real usage pattern the decision didn't anticipate. "I'd have chosen differently" isn't grounds to reopen; "the trigger condition on file just fired" is.
- Open a PR that edits the decision file directly: add a new dated entry under the existing **Choice** section (never delete the prior one — the history of *why* a decision changed is as valuable as the decision itself), and update its status/summary line in [design/README.md](design/README.md).

Two records currently stand against their on-file recommendation, both deliberately: [0005](DECISIONS.md#0005--source-authority-rules) (source authority — the architect chose "query both, never rank" over the recommended authority table) and [0015](DECISIONS.md#0015--developer-surfaces) (developer surfaces — MCP-only over the recommended shared-core-as-library). Both records also carry an explicit backlog note on what would revive the un-chosen option — read that before re-arguing the same case from scratch.

## Where the design spec fits

[ARCHITECTURE.md](ARCHITECTURE.md) § 35 is the map: it lists all 15 decisions with their current chosen answer and links into `design/` for the full reasoning. If the spec's narrative prose (§ 5-33) and a Chosen decision file ever disagree, the decision file wins — flag the mismatch as a documentation-cleanup PR rather than treating it as an open question.

## Code contributions

The contract spike covers one server and one source (see README.md); setup and test running are documented there (`uv venv`, `pytest`). Beyond extending that coverage, the highest-value contribution is sharpening `design/` itself, or filling in Phase 0/1 research gaps named in Design Spec § 36.
