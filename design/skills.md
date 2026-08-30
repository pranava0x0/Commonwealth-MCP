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
- `metadata` carries the machine-readable requirement: `commonwealth.required_capabilities: [zoning.lookup, parcel.lookup]`. Profile generation reads this (a skill's walk defines its profile), and server startup with that profile fails when a listed capability has no route (design/hub-catalog.md § 2). A skill consuming an external server also names it and its `integration_mode`, because a foreign contract is part of the skill's compatibility surface.
- Every skill ships with its bench tasks (§ 5). A skill without evals is a blog post in a trench coat.

Repo layout: `skills/<name>/SKILL.md` in the monorepo for now (architecture.md decision 0007 covers the split trigger). Distribution: standard skill installation paths today; the "Skills over MCP" extension is tracked as the eventual channel so servers can advertise their own workflows (unshipped mechanics; do not build against it yet).

## 2. Skill shape: findings drive the walk

Every Commonwealth skill follows the same internal structure, which reviewers should enforce:

1. **Establish the frame.** Resolve jurisdiction(s) and the entity in question first, using `registry.resolve_jurisdiction` and entity tools; on ambiguity, stop and surface candidates (never guess; the Fairfax trap in jurisdiction-resolution.md § 2.2).
2. **Minimum data walk.** The ordered list of capabilities to consult, each with "what a hit means" and "what an empty result means here" (distinguishing empty-complete from no-coverage using the envelope's coverage block).
3. **Escalation table.** Findings → next workflow, from architecture.md § 18. Escalations follow `next_actions` hints when present but are stated in the skill so they work on envelope data alone.
4. **Output contract.** What the final artifact contains: evidence matrix (claim → source → provenance), unresolved-gaps list, and explicit coverage caveats. A skill's output never states a legal conclusion; it states records found, records absent, and systems unavailable, in those words.
5. **Stop conditions.** When the skill is done, and what it refuses to do (no fee estimates, no "this project will be approved" predictions).

## 3. V1 skills (re-sequenced 2026-08-26)

The first shipped skill is **`parcel-zoning-screen`**: narrow, precisely scoped, and fully covered by the geo vertical (resolve → parcel → zoning → overlay/constraint findings → evidence matrix). The review's naming point is right: a skill must not be called `development-site-due-diligence` until environmental, infrastructure, planning-case, and meeting coverage justify the name — shipping the grand name over a zoning lookup would be exactly the overclaim the envelope exists to prevent. `development-site-due-diligence` and `legislative-impact-analysis` remain the flagship targets, arriving with the coverage that earns them (civic milestone and after); the § 17.1 outlines stay as plans.

Standing rule from the research: each skill's § 2 walk names the *capability* (`zoning.lookup`), not the tool (`geo.find_zoning`), so skills survive tool renames and server re-topologies; capability routing resolves the indirection.

## 4. Anti-patterns (reviewers reject these)

- **Source manuals.** "How to use the Fairfax GIS portal" is registry/manifest content, not a skill.
- **Tool restatement.** A skill that just lists tool names adds context cost and nothing else; the description already routes.
- **Baked-in authority calls.** Which source wins a conflict is registry metadata + surfaced conflict, never skill prose (architecture.md decision 0005 territory; repointed 2026-08-28 from "architecture.md § 17.6", a subsection the consolidation dropped).
- **Call-everything walks.** The escalation table exists so the skill consults sources *because of findings*, not to be thorough; bench scores efficiency.
- **Slop register.** Skill prose is agent-facing but human-reviewed; `tools/check_writing.py` covers `skills/**/SKILL.md`.

## 5. Evaluation

Each skill ships `evals/skills/<name>/`: 3+ tasks that exercise the whole walk, with fixture-backed sources (no live network in CI), scored on the bench dimensions (design/bench.md), with at least one task per failure mode: an ambiguity trap, a no-coverage jurisdiction, a source outage mid-walk. The skill's documented output contract is the scoring rubric; if the contract says "evidence matrix", the scorer checks provenance completeness of that matrix.
