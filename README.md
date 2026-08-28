# Commonwealth-MCP

An MCP suite for Virginia state, county, and municipal public data: servers, tools, and skills that let agents answer real civic questions (zoning, legislation, procurement, permits) against authoritative government sources, with provenance on every answer. Built for indie developers, university researchers, and industry teams who should not each have to rediscover how 133 localities publish their data.

## What works today

Point an MCP client at it, or use the CLI, and ask:

- **Which government covers this?** By name, FIPS code, or coordinates. "Fairfax" returns two candidates and refuses to choose, because Fairfax City is not in Fairfax County — none of Virginia's 38 independent cities sit inside the county they share a name with. A coordinate in a town returns the town *and* its county, since both govern that ground.
- **What is this parcel?** By PIN or point, against four registered assessor systems.
- **How is it zoned?** Fairfax County and Richmond City only. Screening evidence, never a legal determination.
- **Where does this jurisdiction end?** Boundaries statewide, with area, FIPS, and GNIS.
- **What does § 18.2-57 say?** Section text straight from the Code of Virginia.

Every answer carries where it came from, when it was fetched, and what was not searched. An empty result says which kind of empty it is: the records were checked and hold nothing, or no source is registered there at all. Most systems collapse those two into one blank screen, and they are not the same fact.

### Coverage

| Capability | Sources behind it |
|---|---|
| Parcel lookup | Fairfax County, Richmond City, Charles City County, VGIN statewide |
| Zoning lookup | Fairfax County, Richmond City |
| Boundary lookup | VGIN statewide — 133 localities, 191 towns |
| Code of Virginia | law.lis.virginia.gov |

Where a locality publishes its own parcel layer, that layer and VGIN's statewide one are both queried and both shown. Neither is ranked over the other, and a disagreement between two official sources is reported as a disagreement rather than resolved into a single tidier answer.

### What does not work yet

Addresses. There is no geocoder registered, so jurisdictions resolve from names, FIPS codes, and coordinates only. Twelve of Virginia's 133 localities have entries in the jurisdiction table (fourteen rows, counting the state itself and one town), so a coordinate anywhere in the state will place itself, but most places will report that the boundary source knows the government and this project cannot yet route queries to it. Zoning stops at two localities. Everything the design sketches for finance, infrastructure, environment, and people is unbuilt on purpose.

[backlog.md](backlog.md) is the ordered list of what comes next, and [KNOWN_SOURCE_QUIRKS.md](KNOWN_SOURCE_QUIRKS.md) records the things real government data does that its schemas do not predict.

```bash
# from the repo root (--group resolves against ./pyproject.toml)
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e . --group dev
.venv/bin/commonwealth doctor --live
.venv/bin/commonwealth tools call geo.find_zoning --args '{"jurisdiction": "Fairfax County", "pin": "0102 14  0231"}'
.venv/bin/commonwealth serve            # MCP over stdio, default profile
.venv/bin/pytest                        # offline; replays recorded fixtures
```

## The site

[docs/index.html](docs/index.html) is a static page — no build step, no server needed — showing what is registered and a call-by-call audit trail of fourteen real calls: name and coordinate resolutions, an ambiguous one, live parcel and zoning data, a boundary that is two official polygons, a Code of Virginia section, a clean empty result, a registry gap, discovery, and a typed error.

Three parts of it are interactive, and all three run on the recorded data rather than a mock-up of it. The resolver playground answers from the actual `JurisdictionTable.resolve()`, called at build time. The HTTP-exchange view shows the real outbound requests the live calls made to Fairfax County's ArcGIS service, with URLs, parameters, and response shapes. The coverage decoder links each warning and coverage value to whichever recorded call demonstrates it.

```bash
python tools/build_site.py --fixtures   # deterministic, from recordings
python tools/build_site.py --live       # re-queries the real services
python3 -m http.server -d docs          # or just open the file
```

[RESEARCH.md](RESEARCH.md#6-how-the-projects-own-site-compares) sets it against nepa-mcp, Power-Agent, civic-ai-tools, and others.

## Where to start

| You want | Read |
|---|---|
| What the system is and how it fits together | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Why it is shaped that way, with the rejected alternatives intact | [DECISIONS.md](DECISIONS.md) |
| The evidence behind those decisions | [RESEARCH.md](RESEARCH.md) |
| The per-feature contracts the code is written against | [design/](design/README.md) |
| How to propose a decision, or argue a settled one should reopen | [CONTRIBUTING.md](CONTRIBUTING.md) |

Four documents, in dependency order: research produced decisions, decisions produced the architecture, the architecture is implemented by the specs in `design/`. Each links back to the one behind it.

Day-to-day: [backlog.md](backlog.md) is what's next, [issues.md](issues.md) is what's broken, [KNOWN_SOURCE_QUIRKS.md](KNOWN_SOURCE_QUIRKS.md) is what government data does that its schemas don't predict, and [docs/RUNLOG.md](docs/RUNLOG.md) is what happened when.

## Repo layout

```text
├── ARCHITECTURE.md   what the system is: servers, provenance contract,
│                     source registry, adapters, the phased plan
├── DECISIONS.md      why: one record per architectural choice, every
│                     credible option kept on the page after the choice
├── RESEARCH.md       the evidence those choices were made from
├── design/           per-feature specs, one contract each; the code cites
│                     them by name, and each names the decisions it needs
├── src/commonwealth/ the implementation
├── sources/          the source registry: manifests and the jurisdiction
│                     table, versioned and reviewed like code
├── tests/            offline, replaying recorded government responses
├── docs/             the static site and the run log
├── research/raw/     script output, not committed; regenerate with the
│                     scripts below
└── tools/            research and site-build scripts (stdlib Python)
```

## Reproducing the research

The searches behind `research/` are scripts, not lore — see [RESEARCH.md](RESEARCH.md):

```bash
python3 tools/search_hn.py
python3 tools/search_github.py
python3 tools/fetch_mcp_registry.py
python3 tools/check_writing.py     # the register lint every doc here passes
```
