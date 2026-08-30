# Contributing

Thanks for looking. Here is what is most useful, and how the moving parts
fit together.

## Start here

[README.md](README.md) says what works today. The open issues say what is
next:

- [All open issues](https://github.com/pranava0x0/Commonwealth-MCP/issues)
- [`good first issue`](https://github.com/pranava0x0/Commonwealth-MCP/issues?q=is%3Aopen+label%3A%22good+first+issue%22)
- [`priority: high`](https://github.com/pranava0x0/Commonwealth-MCP/issues?q=is%3Aopen+label%3A%22priority%3A+high%22)

Setup and tests are in the README. The tests replay recorded government
responses, so `pytest` works with no network.

## Adding a government source

The most valuable contribution, and the one this project is shaped around.

A source is a YAML manifest under `sources/`. It names a government
service, what it publishes, and what the publisher's terms allow. Nothing
about it is code.

Read [design/source-registry.md](design/source-registry.md) first. The
parts that matter most:

- A manifest starts as `declared_state: proposed`. It only becomes
  `active` once someone has read the publisher's actual terms and
  recorded what they say.
- If the terms are unclear, record that. A manifest that says "no terms
  page found, contact is X" is useful. One that invents a terms page is
  worse than nothing.
- Field names come from the source, not from what would be convenient.

Existing manifests in `sources/local/` and `sources/state/` are the
working examples.

## Reporting something wrong with the data

If a government source returns something surprising, that is worth
recording even if nothing needs to change in the code.
[design/source-quirks.md](design/source-quirks.md) collects these. Each
entry says what was observed, when, why it matters, and what the code does
about it.

Two rules for that file: only things actually observed, with the date, and
a test name if the quirk changes what the code does.

## Changing the architecture

The architecture and every decision behind it are in
[design/architecture.md](design/architecture.md). Fourteen of the fifteen
decisions are settled; 0009 is deliberately left open.

**To propose a new decision**, open a PR that adds a record to Part 2 in
the same shape as the existing ones:

1. **Context** — the problem in a few sentences, pointing at the spec
   section or code it affects.
2. **Every option worth considering**, each with arguments for and
   against, backed by something concrete: a benchmark, a peer project's
   choice, a spec citation. Options are never deleted after a choice is
   made. Six months later, the useful question is what was given up.
3. **A recommendation**, and what would change it.
4. A row in the index table at the top of Part 2, with status **Open**.

**To reopen a settled decision**, you need new evidence rather than a
different preference. Read the record's "what would change this" line
first. If your argument does not address the condition it names, it is not
ready.

New evidence looks like: a benchmark result, an upstream fact that
changed (a library went stable, a client added protocol support, a
source's terms changed), or a usage pattern the decision did not
anticipate.

Open a PR that adds a new dated entry under the existing **Choice**
section. Do not delete the old one. Why a decision changed is worth as
much as what it changed to.

Two records currently stand against the recommendation written on them,
both deliberately:

- [0005](design/architecture.md#0005--source-authority-rules), source
  authority. Query both sources and show both, rather than maintaining a
  table of which one wins.
- [0015](design/architecture.md#0015--developer-surfaces), developer
  surfaces. MCP only, rather than also shipping the core as a library.

Both records note what would revive the option that lost. Read that before
re-arguing the case from scratch.

## Licensing and sign-off

Three licenses apply, to three different kinds of thing:

| What | License |
|---|---|
| Code (`src/`, `tools/`, `tests/`) | Apache-2.0, see [LICENSE](LICENSE) |
| The source registry you wrote (`sources/`) | CC0-1.0, see [sources/LICENSE](sources/LICENSE) |
| Documentation prose | CC-BY-4.0, see [docs/LICENSE-DOCS](docs/LICENSE-DOCS) |

Recorded government responses under `tests/fixtures/` are not covered by
any of those. They are the publisher's content under the publisher's
terms, inventoried in [THIRD_PARTY_DATA.yml](THIRD_PARTY_DATA.yml). That
file is generated:

```bash
python3 tools/build_third_party_data.py
```

**Sign your commits off.** Every commit needs a Developer Certificate of
Origin line, which `git commit -s` adds:

```
Signed-off-by: Your Name <your.email@example.com>
```

It states that you wrote the contribution, or have the right to submit it
under these licenses. The full text is at
[developercertificate.org](https://developercertificate.org/).

If you are registering a government source, that sign-off covers the
manifest you wrote. It does not and cannot cover the government data
itself.

## Before you open a pull request

Two things go stale on their own and both are checked in CI, so it is
cheaper to run them yourself than to read about them in a failed build.

**Rebuild the site.** `docs/` is published — GitHub Pages serves it from
`main` — so it ships in the same PR as the change it describes, never in
a follow-up.

```bash
.venv/bin/python tools/build_site.py --fixtures
```

Run it after anything that touches sources, tools, capabilities, or the
jurisdiction table. Never hand-edit `docs/data/*.json`; the page embeds
those files and a test compares the two copies byte for byte.

If you added a tool, add a `DEMO_CALLS` entry for it in
`tools/build_site.py`. The page walks one recorded call per tool and a
test derives that list from the tool registry, so a tool with no demo
fails the build. Pick a call that shows what the tool gets right, not
that it runs.

**Run the writing checker**, every time prose changes rather than once at
the end:

```bash
python3 tools/check_writing.py          # the Markdown tree and the site
python3 tools/check_writing.py --code   # adds comments and docstrings; CI runs this
python3 tools/check_writing.py --issues # open GitHub issues
```

Prose here means everything with sentences in it: Markdown, code comments
and docstrings, tool descriptions and error strings, commit messages, PR
bodies, and issue bodies.

## Writing

The checker reads the docs and the site and flags the habits this project
keeps falling into: slogan headings, sentences that state a principle
instead of a fact, paragraphs with no verb in them, and cross-references
welded onto the end of a sentence with a dash.

Every rule in it exists because prose that shipped here tripped it. If a
rule fires on something that is genuinely load-bearing, that is worth
arguing about in the PR. The rules are not sacred; they are a record of
what went wrong before.

When prose does get past it, add a rule with the offending sentence as
its test case in `tests/test_writing_lint.py`. A checker with no test
quietly stops catching things.
