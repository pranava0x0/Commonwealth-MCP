# What is in this folder

This folder holds the published website. GitHub Pages serves it from
`main`, which is why it is named `docs/`: the name is the publishing
convention rather than a description, and it is the one thing here a
reader is likely to misread. The documentation is in `design/`.

| File | What it is |
|---|---|
| `index.html` | The site at pranava0x0.github.io/Commonwealth-MCP. Static, no build step; `tools/build_site.py` writes the data it embeds |
| `data/` | Generated. Counts, one recorded call per tool, and the resolver's answers. Never hand-edited; a test compares the committed copies against what the registries produce |
| `llms.txt` | The same summary written for an AI assistant reading the project |
| `RUNLOG.md` | What happened when, one entry per working session |
| `audits/` | Measurements kept because a claim rests on them: the onboarding-cost table, the falsified centroid property, and the weekly upstream-drift reports |
| `audits/probe-history.json` | Every feature count ever observed, per source and layer. Appended to, never rewritten; it is what lets a health floor rest on a range instead of one reading |

The documentation is elsewhere:

- [../README.md](../README.md) — what this project is and how to run it
- [../design/](../design/README.md) — how it works, why, and the contract for each feature
- [../research/](../research/README.md) — the evidence the design was made from
