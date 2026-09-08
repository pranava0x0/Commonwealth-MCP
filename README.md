# Commonwealth-MCP

Python tools for Virginia public data, with a command-line interface and an
MCP server for AI assistants. For policy researchers and developers building
applications for Virginia residents.

[Try the browser demos](https://pranava0x0.github.io/Commonwealth-MCP/#try)
· [Search the tools](https://pranava0x0.github.io/Commonwealth-MCP/#tools)
· [Run examples](examples/README.md)
· [Add a data source](CONTRIBUTING.md)
· [Design and remaining work](design/README.md)

Independent project. Not affiliated with or maintained by the Commonwealth
of Virginia.

## Start here

MCP (Model Context Protocol) lets an AI client call functions supplied by a
server. Here, those functions query government records and return structured
results. The same functions are callable from Python and from the CLI
without an AI model; they are not yet a supported public API (decision
0015 in [design/architecture.md](design/architecture.md)), so a release
may rename them.

The browser demos use recorded responses and require no installation.
To run the tools locally, install [uv](https://docs.astral.sh/uv/getting-started/installation/)
and Git, then run these commands in a macOS or Linux terminal:

```bash
git clone https://github.com/pranava0x0/Commonwealth-MCP.git
cd Commonwealth-MCP
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e . --group dev
.venv/bin/python examples/one_address_every_question.py
```

The example prints results for an address in Sterling: a parcel found in
statewide records, a zoning coverage gap, and no matching landmark records
within the query radius. It runs offline by default. Add `--live` to query
the government services. See [examples/](examples/README.md) for five other
workflows.

Keep this checkout: the current runtime loads source manifests and skills
from it. A standalone wheel install is not yet supported. On Windows,
virtual-environment executables live under `.venv\Scripts\`.

## What works

| Question | Registered sources |
|---|---|
| Which government covers a place? | Names, FIPS codes, addresses, ZIP codes and coordinates; the table contains 133 counties and independent cities and 189 towns |
| What parcel is here? | Fairfax County, Richmond City, Charles City County, the Town of Leesburg, and VGIN statewide parcels |
| How is a parcel zoned? | Fairfax County, Richmond City, and the Towns of Leesburg and Vienna. A point in Vienna returns the town's layer and the county's, both unranked |
| Which address points, buildings, roads or public places are nearby? | VGIN statewide layers; VDOT road routes |
| Which water-quality stations are nearby? | DEQ monitoring stations, including historical stations |
| Where is a government boundary? | VGIN locality and town polygons |
| What does a Code of Virginia section say? | Section lookup by citation |

A registered statewide layer does not guarantee complete or current records
for every place. Read each result's sources, dates, coverage and warnings.
School attendance zones, transit service areas and other special districts
are not resolved by the locality table.

Virginia's independent cities are separate from counties. A mailing city
may differ from the governing locality, and towns can span counties.
Ambiguous names return candidates for the caller to choose from.

When two registered sources cover a query, both can be returned. Their
records remain separate. Zoning results describe GIS records; confirm
applicable requirements with the locality and its adopted ordinance.

No matching records means the query found none in the sources checked.
A registry gap means no source is registered for that question and place.
Neither establishes that a feature or service does not exist.

## Use an AI client

Preview a client configuration change:

```bash
.venv/bin/commonwealth configure claude-code --dry-run
```

Remove `--dry-run` to write it. Other supported configuration targets are
`claude`, `codex`, `cursor`, and `vscode`. Existing server entries are
preserved. The server uses local stdio transport:

```bash
.venv/bin/commonwealth serve
```

Client configuration support does not imply hosted access. There is no
public hosted endpoint in this project.

## Use the CLI or Python

A live CLI query. A PIN is the number a locality gives a parcel; the
spacing inside it is the county's and matters:

```bash
.venv/bin/commonwealth tools call geo.find_parcel \
  --args '{"jurisdiction": "Fairfax County", "pin": "0102 14  0231"}'
```

The same capability in Python:

```python
import asyncio
from commonwealth.runtime import load_context
from commonwealth.domains.geo import find_parcel

async def main():
    result = await find_parcel(
        load_context(), jurisdiction="Fairfax County", pin="0102 14  0231")
    print(result.model_dump_json(indent=2))

asyncio.run(main())
```

Results include data, source references, retrieval dates, coverage and
warnings. Large retrieved results may have a `commonwealth://` resource
handle with an expiry, normally 24 hours. A handle contains what was
retrieved; it does not remove upstream query limits.

## What remains

Most directly integrated local sources are concentrated in five localities:
Fairfax County, Richmond City, Charles City County, and the Towns of
Leesburg and Vienna. Adding another locality's parcel or zoning layer is the
most useful contribution and the best-documented path
([CONTRIBUTING.md](CONTRIBUTING.md)).

The next priority in the project's own order is packaging: the runtime finds
source manifests, the jurisdiction table and skills relative to the checkout,
so a wheel installed anywhere else has the Python and none of the data. That
is what has to be true before the server is published
([issue #40](https://github.com/pranava0x0/Commonwealth-MCP/issues/40)).
State legislation search, local meetings and full-text Code search are
tracked in
[issues #11–13](https://github.com/pranava0x0/Commonwealth-MCP/issues?q=is%3Aissue+is%3Aopen).

Budgets, procurement, school statistics, transit, permits and service
requests need source discovery and adapters. They are proposed areas of
work, not available tools. The
[development priorities](design/architecture.md#39-delivery-sequence)
explain the order and acceptance criteria.

## Develop and contribute

```bash
COMMONWEALTH_DENY_NETWORK=1 .venv/bin/pytest
.venv/bin/python tools/build_site.py --fixtures
python3 tools/check_writing.py --code
```

The tests replay recorded government responses. To check current service
availability separately, run `.venv/bin/commonwealth doctor --live`.

| Location | Purpose |
|---|---|
| [examples/](examples/README.md) | Runnable workflows |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Source onboarding and development checks |
| [design/](design/README.md) | Current architecture, contracts and planned work |
| `src/commonwealth/` | Python implementation |
| `sources/` | Source manifests and jurisdiction records |
| `skills/` | Instructions for multi-tool workflows |
| `tests/`, `evals/` | Offline tests and workflow evaluations |
| [docs/](docs/README.md) | Published site and audit records |
| [research/](research/README.md) | Historical research; verify dated claims before reuse |

## License

Code: Apache-2.0. Registry: CC0. Documentation prose: CC-BY-4.0.
Recorded government responses retain their publishers' terms. See
[NOTICE](NOTICE) and [THIRD_PARTY_DATA.yml](THIRD_PARTY_DATA.yml).
