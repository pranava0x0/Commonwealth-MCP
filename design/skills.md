# Spec: Commonwealth Skills

**Plugs into:** architecture.md § 17 (Skills Architecture), § 18 (Escalation Logic)
**Status:** Draft for review.
**Why this exists:** Tools answer questions; skills encode how a professional would chain the questions, what to verify, and when to escalate. The research corpus is blunt about the split: description-rich tools plus workflow knowledge beat either alone, and skills are where domain experts contribute without touching server code (Power-Agent's PowerSkills is the strongest prior art; ../research/README.md part 4 § 3 covers why skills complement rather than replace the MCP layer).

---

## 1. Packaging: the agentskills.io spec, verbatim

Commonwealth Skills are standard Agent Skills (the spec is vendor-neutral at agentskills.io as of 2026; ../research/README.md part 1 § 5). House rules layered on top:

- `name`: lowercase-hyphen, matches directory, ≤64 chars. Namespace by outcome, not by agency: `development-site-due-diligence`, never `vdot-workflows`.
- `description`: covers what AND when, keyword-rich because ~100 tokens of metadata is all a host loads until activation. Write it like a tool description: the router reads it, not a human.
- Body under 500 lines; deep material goes to `references/` one level down (checklists, per-domain source notes, glossaries of Virginia terms of art like "by-right", "proffer", "2232 review").
- `scripts/` only for deterministic helpers a model reliably fumbles (e.g., chronology sorting/merging of mixed-date-type events). Scripts follow this repo's Python standards and stay optional: a skill must degrade gracefully on hosts that refuse script execution.
- `compatibility` names required Commonwealth servers ("Requires commonwealth-geo and commonwealth-civic v0.x tools") so a host missing them can say so instead of flailing.
- `metadata` carries the machine-readable requirement: `commonwealth.required_capabilities: [zoning.lookup, parcel.lookup]`. Profile generation reads this (a skill's walk defines its profile), and server startup with that profile fails when a listed capability has no route (design/hub-catalog.md § 2). Half of that is built as of 2026-09-01: startup reads every skill's list and warns when no active source answers one. Profiles stay hand-written for the reason the dated amendment on decision 0002 gives. A skill consuming an external server also names it and its `integration_mode`, because a foreign contract is part of the skill's compatibility surface.
- Every skill ships with its bench tasks (§ 5). A skill without evals is a blog post in a trench coat.

Repo layout: `plugins/commonwealth-mcp/skills/<name>/SKILL.md` in the monorepo for now (architecture.md decision 0007 covers the split trigger).

It sat at `skills/` at the root until 2026-09-08, when #53 built the plugin bundle. A client discovers a plugin's skills by convention, in a `skills/` directory under the plugin root, so the skills moved under the bundle rather than being copied into it. `pyproject.toml` force-includes that directory into the wheel at `commonwealth/_data/skills` and `runtime.SKILLS_DIR` prefers the checkout, so the repo holds one copy and the package holds one.

Distribution: the plugin bundle, which installs the server and the skills together, and the standard skill installation paths for a client with no plugin system. The "Skills over MCP" extension is tracked as the eventual channel so servers can advertise their own workflows (unshipped mechanics; do not build against it yet).

## 2. Skill shape: findings drive the walk

Every Commonwealth skill follows the same internal structure, which reviewers should enforce:

1. **Establish the frame.** Resolve jurisdiction(s) and the entity in question first, using `registry.resolve_jurisdiction` and entity tools; on ambiguity, stop and surface candidates (never guess; the Fairfax trap in jurisdiction-resolution.md § 2.2).
2. **Minimum data walk.** The ordered list of capabilities to consult, each with "what a hit means" and "what an empty result means here" (distinguishing empty-complete from no-coverage using the envelope's coverage block).
3. **Escalation table.** Findings → next workflow, from architecture.md § 18. Escalations follow `next_actions` hints when present but are stated in the skill so they work on envelope data alone.
4. **Output contract.** What the final artifact contains: evidence matrix (claim → source → provenance), unresolved-gaps list, and explicit coverage caveats. A skill's output never states a legal conclusion; it states records found, records absent, and systems unavailable, in those words.
5. **Stop conditions.** When the skill is done, and what it refuses to do (no fee estimates, no "this project will be approved" predictions).

## 3. V1 skills (re-sequenced 2026-08-26)

**`parcel-zoning-screen` shipped 2026-09-01** (#27) at `plugins/commonwealth-mcp/skills/parcel-zoning-screen/SKILL.md`, with five tasks in `evals/skills/parcel-zoning-screen/` and a replay of its four fixture-backed cases in `tests/test_skills.py`. It is the first skill, and it is: narrow, precisely scoped, and fully covered by the geo vertical (resolve → parcel → zoning → overlay/constraint findings → evidence matrix). The review's naming point is right: a skill must not be called `development-site-due-diligence` until environmental, infrastructure, planning-case, and meeting coverage justify the name — shipping the grand name over a zoning lookup would be exactly the overclaim the envelope exists to prevent. `development-site-due-diligence` and `legislative-impact-analysis` remain the flagship targets, arriving with the coverage that earns them (civic milestone and after); the § 17.1 outlines stay as plans.

Standing rule from the research: each skill's § 2 walk names the *capability* (`zoning.lookup`), not the tool (`geo.find_zoning`), so skills survive tool renames and server re-topologies; capability routing resolves the indirection.

Step 1 is the exception, noticed 2026-09-01 while writing the first skill. It is the one step with no capability id behind it, because resolving a name reads the jurisdiction table and the table is not a registered source. A skill cannot declare a requirement for it the way it declares `zoning.lookup`.

Resolving a *point* uses `boundary.lookup` and resolving an *address* uses `geocode.address`, and a skill can declare those two. So step 1 is written as "resolve the jurisdiction", which names neither a tool nor a capability that does not exist.

### Candidate skills, listed 2026-09-07

Written here rather than filed as issues, so that § 4 is applied before
anything is built. Each row names the capabilities its walk would declare
and the eval tasks that could ship from fixtures already on disk.

| Skill | What it packages | Required capabilities | Evals available today |
|---|---|---|---|
| `code-section-check` | Read one Code of Virginia section from a citation in any common form, report the text and the section's own history line, and say what the lookup cannot establish: pending amendments, local ordinances, legal effect. | `code_section.lookup` | The recorded section; the missing-section page; a title-only citation, refused because there is no full-text search; a local-ordinance citation, which is not the Code; an overreach question. |
| `coverage-check` | Before answering about a place or a topic, establish what the registry can answer there, and name where the real-world answer lives where it cannot. | `boundary.lookup`, with the registry tools | Craig County (registry gap); VDH (inventory only); DEQ (terms gap); an unknown capability (typed error); a degraded source. |
| `source-onboarding` | Register a government source the way CONTRIBUTING.md and GOVERNANCE.md describe: probe, sample, validate, terms review, classification, cost-log row, quirk entry. | None; it drives the CLI | Given a service URL, produce a manifest that passes `sources validate`; given a fixture, list what a reviewer must classify. |
| `drift-triage` | Read a weekly audit report and the readings history, classify each finding as churn, schema drift, outage, or quirk, and propose the floor change or the quirks entry. | None; it reads committed reports | The 2026-09-02 and 2026-09-07 reports. |

`source-onboarding` is the nearest of the four to the source-manual
anti-pattern, so it stays a workflow over the CLI and never a guide to one
publisher. The two flagship skills cannot start until the civic sources
land (#11, #13).

### Shipped 2026-09-08 (#54)

These build three of the candidates above, in the order #54 set, and each
carries four eval tasks under `evals/skills/<name>/`.

- **`coverage-check`** — the row above, built as written. It runs entirely
  against the registry, so it costs no government request and answers
  while every upstream is down. It declares `boundary.lookup` because its
  first step resolves the place; the registry tools it then uses are not
  capability-routed, which is § 3's step-1 exception showing up again.
- **`code-topic-walk`** — the `code-section-check` row, widened from
  "read a citation" to "reach one". Reading a citation is a single tool
  call and adds nothing a model cannot already do; the walk that earns a
  skill is the descent through the Code's own contents to a citation the
  reader does not have, and the refusal when the descent does not reach
  one. Named for what it does rather than for the row it came from.
- **`federal-site-screen`** — the first skill spanning two servers. The
  Virginia half is this registry; the federal half (FEMA flood, USACE
  wetlands, EPA cleanup sites) is nepa-mcp's, and the walk's whole
  difficulty is keeping the two sets of citations apart. Its §&nbsp;3 names
  the partner's tool names, which the standing rule above allows: those
  tools are outside this registry, so there is no capability id to name
  instead.

Four cross-server candidates from #54 are still unbuilt: Census
demographics, LegiScan bills, CourtListener case law, and filing a
coverage gap as a GitHub issue. Each waits on the review this section
asks for.

## 4. Anti-patterns (reviewers reject these)

- **Source manuals.** "How to use the Fairfax GIS portal" is registry/manifest content, not a skill.
- **Tool restatement.** A skill that just lists tool names adds context cost and nothing else; the description already routes.
- **Baked-in authority calls.** Which source wins a conflict is registry metadata + surfaced conflict, never skill prose (architecture.md decision 0005 territory; repointed 2026-08-28 from "architecture.md § 17.6", a subsection the consolidation dropped).
- **Call-everything walks.** The escalation table exists so the skill consults sources *because of findings*, not to be thorough; bench scores efficiency.
- **Slop register.** Skill prose is agent-facing but human-reviewed; `tools/check_writing.py` covers `plugins/*/skills/**/SKILL.md`.

## 5. Evaluation

Each skill ships `evals/skills/<name>/`: 3+ tasks that exercise the whole walk, with fixture-backed sources (no live network in CI), scored on the bench dimensions (design/bench.md), with at least one task per failure mode: an ambiguity trap, a no-coverage jurisdiction, a source outage mid-walk. The skill's documented output contract is the scoring rubric; if the contract says "evidence matrix", the scorer checks provenance completeness of that matrix.
