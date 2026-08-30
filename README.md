# Commonwealth-MCP

Virginia government data, available to AI agents through the Model Context
Protocol.

Ask which local government covers a spot on the map, what a parcel record
says, how a parcel is zoned, or what a section of the Code of Virginia
says. Every answer names the government system it came from and the date
it was fetched.

> Independent project. Not affiliated with or maintained by the
> Commonwealth of Virginia.

## Why this exists

Virginia has 133 counties and independent cities. Each one publishes its
data its own way: different platforms, different field names, different
rules about what you may do with it. Anyone building something on top of
Virginia public data has to work that out first, and everyone works it out
separately.

This project does it once and writes down what it learned.

## Try it

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e . --group dev
```

Check that the registered government services are reachable:

```bash
.venv/bin/commonwealth doctor --live
```

Ask a real question:

```bash
.venv/bin/commonwealth tools call geo.find_zoning \
  --args '{"jurisdiction": "Fairfax County", "pin": "0102 14  0231"}'
```

Point an AI client at it. This writes the client's config file, shows you
the change first, and leaves any other servers you have configured alone:

```bash
.venv/bin/commonwealth configure claude-code --dry-run
```

Drop `--dry-run` to write it. `claude`, `codex`, `cursor` and `vscode` work
too. Or run the server directly, over stdio:

```bash
.venv/bin/commonwealth serve
```

The tests replay recorded government responses, so they run offline:

```bash
.venv/bin/pytest
```

## What it can answer today

| Question | Coverage |
|---|---|
| Which government covers this? | By name, FIPS code, street address, ZIP, or coordinates: all 133 localities and 191 towns |
| What is at this address? | Statewide address points |
| What is this parcel? | Fairfax County, Richmond City, Charles City County, VGIN statewide |
| How is it zoned? | Fairfax County and Richmond City |
| Where does this jurisdiction end? | Statewide: 133 localities, 191 towns |
| What does § 18.2-57 say? | The full Code of Virginia |

Some examples of what that looks like in practice:

**A mailing address is not a government.** "Alexandria, VA 22310" is a
Fairfax County address. Ask about it and the answer is Fairfax County,
with a note saying the mailing city and the government differ. A ZIP that
spans several localities comes back as all of them, because a ZIP is a
delivery route and picking one would be a guess.

**Ambiguous names come back ambiguous.** Ask about "Fairfax" and you get
both candidates back. Fairfax City is not inside Fairfax County —
it is a separate government. None of Virginia's 38 independent cities sit
inside the county they share a name with, and this trips up almost every
system that handles Virginia data.

**A point in a town returns the town and the county.** Both govern that
ground, so both are in the answer.

**Two official sources that disagree are both shown.** Where a locality
publishes its own parcel layer and VGIN publishes a statewide one, both
are queried. Neither is ranked above the other, and a disagreement is
reported as a disagreement.

**An empty answer says which kind of empty it is.** Either the records
were searched and nothing matched, or no source is registered for that
place at all. Most systems show the same blank screen for both. They are
different facts, and only one of them means "there is nothing there".

**Zoning answers are screening evidence.** They report what the county's
GIS layer says. The adopted ordinance is what governs, and the answer says
so every time.

## What it cannot do yet

**Data for most localities.** Every one of the 133 counties and
independent cities is in the jurisdiction table, along with all 191
incorporated towns, so a name or a coordinate anywhere in Virginia finds
the right government. What most of them do not have is a source of their
own: three localities publish a parcel layer this project reads, and the
rest are answered by VGIN's statewide layers or not at all.

**Zoning outside two localities.** Fairfax County and Richmond City are
registered. Everywhere else returns a registry gap.

**Everything else in the design.** Finance, infrastructure, environment,
and people are sketched in the architecture and not built.

[Open issues](https://github.com/pranava0x0/Commonwealth-MCP/issues) is
the list of what comes next, ordered by priority label.

## The demo site

[docs/index.html](docs/index.html) is a static page with no build step. It
shows what is registered, and walks through fourteen real recorded calls
one at a time: successful lookups, an ambiguous jurisdiction, an empty
result, a registry gap, and a typed error.

Three parts of it are interactive, and all three run on recorded data
rather than a mock-up. The jurisdiction resolver calls the real
`JurisdictionTable.resolve()` at build time. The HTTP view shows the
actual requests that went to Fairfax County's ArcGIS service. The coverage
decoder links each warning code to a call that produced it.

```bash
python tools/build_site.py --fixtures   # rebuild from recordings
python tools/build_site.py --live       # re-query the real services
python3 -m http.server -d docs          # or just open the file
```

## Where things are

| You want | Read |
|---|---|
| How the system works and why | [design/architecture.md](design/architecture.md) |
| The contract for one feature | [design/](design/README.md) |
| Odd things real government data does | [design/source-quirks.md](design/source-quirks.md) |
| The research the design came from | [research/](research/README.md) |
| What happened when | [docs/RUNLOG.md](docs/RUNLOG.md) |
| How to contribute | [CONTRIBUTING.md](CONTRIBUTING.md) |

```text
design/       how it works, why, and the per-feature contracts
src/          the implementation
sources/      the source registry: one manifest per government service,
              plus the jurisdiction table, reviewed like code
tests/        offline, replaying recorded government responses
research/     the evidence behind the design
docs/         the demo site and the run log
tools/        research and site-build scripts, stdlib Python only
```

## License

Code is Apache-2.0. The source registry is CC0. Documentation prose is
CC-BY-4.0. Recorded government responses belong to their publishers and
keep those publishers' terms.

[NOTICE](NOTICE) says which applies to what, and
[THIRD_PARTY_DATA.yml](THIRD_PARTY_DATA.yml) lists every government source
this repo redistributes anything from.

## Reproducing the research

The searches behind `research/` are scripts, so you can re-run them:

```bash
python3 tools/search_hn.py
python3 tools/search_github.py
python3 tools/fetch_mcp_registry.py
```

There is also a writing checker. It reads the docs and the site and flags
the habits this project keeps falling into:

```bash
python3 tools/check_writing.py
```
