# What is in this folder

This folder holds the published website. GitHub Pages serves it from
`main`, which is why it is named `docs/`: the name is the publishing
convention rather than a description, and it is the one thing here a
reader is likely to misread. The documentation is in `design/`.

| File | What it is |
|---|---|
| `index.html` | The landing page at pranava0x0.github.io/Commonwealth-MCP: what it answers, the quick start, one recorded walk, the workflows, and the coverage table |
| `tools.html` | The tool reference, searchable and grouped by package |
| `sources.html` | The source registry, with each source's known limitations, and the places list |
| `examples.html` | The recorded call trail, the coverage and warning decoder, and the jurisdiction resolver |
| `demos.html` | Five short apps over the same recorded trail: screen a site, find a public meeting, walk the Code, check coverage, read an envelope. Each app's steps are resolved to trail positions by `tools/build_site.py`, which fails the build if one does not resolve |
| `assets/` | The stylesheet, the script, and the images every page shares, including `og-image.jpg` for link previews. Hand-written; `tools/build_site.py` never touches them |
| `data/` | Generated. `core.json` is embedded in every page; `coverage.json`, `audit-demo.json` and `resolver-demo.json` are fetched by the page that shows them. Never hand-edited; a test compares the committed copies against what the registries produce |
| `llms.txt` | The same summary written for an AI assistant reading the project |
| `sitemap.xml`, `robots.txt` | Generated from the page list in `tools/build_site.py`, so a new page is in the sitemap without anyone adding it |
| `RUNLOG.md` | What happened when, one entry per working session |
| `audits/` | Measurements kept because a claim rests on them: the onboarding-cost table, the falsified centroid property, the page-weight measurement behind the four-page split, and the weekly upstream-drift reports |
| `audits/probe-history.json` | Every feature count ever observed, per source and layer. Appended to, never rewritten; it is what lets a health floor rest on a range instead of one reading |

The documentation is elsewhere:

- [../README.md](../README.md) — what this project is and how to run it
- [../design/](../design/README.md) — how it works, why, and the contract for each feature
- [../research/](../research/README.md) — the evidence the design was made from
