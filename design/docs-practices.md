# Spec: Documentation Practices

**Plugs into:** every public artifact; enforced by `tools/check_writing.py` and the diagram conventions in architecture.md § D6 (the "Flows, drawn" appendix — repointed 2026-08-28; "§ 6" had collided with the spec body's Recommended Architecture section).
**Status:** Draft for review.
**Why this exists:** Two research findings make docs a first-class engineering surface. First, generated-sounding prose now costs projects credibility outright ("obviously generated slop... makes me completely skip the project"; ../research/README.md part 4 § 10). Second, tool descriptions and error strings are *agent-facing docs* whose quality measurably moves task success (Anthropic's description-refinement results; ../research/README.md part 1 § 4). The practices below treat human docs and agent-facing strings as one discipline with two audiences.

---

## 1. Structure: primitives first

The praised recovery in the Octelium launch thread was a page that "starts by explaining the core primitives... and builds up from there." Commonwealth's doc tree follows that shape:

```text
docs/
├── index.md            # what this is, who it serves, 90-second orientation
├── primitives.md       # source manifest → adapter → tool → skill, one concept each
├── quickstart.md       # install → doctor → first query, measured against 10 minutes
├── architecture.md     # the diagrams (today they live in root architecture.md's
│                       #   "Flows, drawn" appendix; extract or link when this tree is built)
├── trust.md            # what Commonwealth can/cannot touch, terms policy, security posture
├── contributing/
│   ├── sources.md      # the manifest workflow, aimed at data contributors
│   └── code.md
└── reference/          # generated: tool pages, envelope schema, capability vocabulary
```

Rules:

- `trust.md` is page-one material, linked from the README's first screen: read-only scope, registry allowlisting, no arbitrary outbound, what gets logged. Vetting anxiety is the default posture of adopters (../research/README.md part 4 § 4); answer it before it's asked.
- `reference/` is generated from code (tool registries, schemas) by the docs build; hand-edits to generated pages are build failures. Prose pages explain; generated pages enumerate. Nothing enumerates by hand.
- Every feature page answers, in order: what it does, when to use it, one worked example with real Virginia data, limits. No page opens with the project's mission statement.

## 2. Register: the anti-slop gate is part of CI

- `tools/check_writing.py` runs over docs, specs, decisions, skills prose, and (once code exists) tool descriptions and error strings extracted from the tool registry. FAIL findings block; WARN findings need a human reading, and exemptions carry written reasons in the script's allowlist.
- The register rules enforced by `tools/check_writing.py` apply in full: lead with the specific (a number, a county, a date), no marketing vapor, no negation slogans, no announced virtue. "Tracks 133 Virginia localities' zoning through one tool contract" beats any adjective.
- READMEs get the strictest read: they are the artifact the community judges first, and the corpus shows judgment is swift.
- **The WARN count is the gate, and the script has no diff mode** (learned 2026-08-28). "0 banned, N review" is only meaningful against the count before the edit, and `check_writing.py` scans the working tree with no way to ask "what did this change add?" To claim the count is unchanged, save the edited file, put HEAD's version in its place, run the script, then restore — the restore is the step that is easy to forget and it clobbers the edit: `cp <path> /tmp/new && git show HEAD:<path> > <path> && python tools/check_writing.py; cp /tmp/new <path>`. Doing this caught two `wall-paragraph` WARNs that a single correction paragraph had added — both fixed by splitting the paragraph, not by rewording.

## 3. Agent-facing strings are documentation

- **Tool descriptions** follow a template: one-line what; when-to-use (and when NOT, naming the better tool); argument notes with Virginia-specific examples ("jurisdiction accepts names, FIPS, or `va:` IDs; Fairfax City and Fairfax County are different places"); result-shape note naming the envelope. Descriptions are versioned with the tool contract and covered by Tier 2 bench tasks, so a description edit that hurts selection shows up as a regression.
- **Error strings** name the failure class, what it means in government-data terms, and the next move (design/provenance-envelope.md § 7's example is the pattern).
- **`llms.txt`** ships at the docs root, generated from the same registries, so agent consumers get the orientation page in their own format (house pattern from the base files, and it doubles as the docs' own smoke test: if `llms.txt` generation breaks, reference generation broke).

## 4. Freshness discipline

- Every research-derived claim in docs carries its as-of date; numbers copied from external posts name the source and date (the practice this repo's research docs already follow).
- Generated reference pages carry the generator's input versions (tool contract, envelope version).
- A docs page describing behavior ships in the same PR as the behavior; "docs to follow" merges are the drift machine the base files warn about.

## 5. Diagrams

architecture.md § D6 conventions govern ("Flows, drawn" appendix): Mermaid-in-Markdown, one question per diagram, real artifact names, no boxes without specs. Diagrams are reviewed like prose: a reviewer who cannot answer the diagram's stated question from the diagram rejects it.
