# Commonwealth-MCP

Python tools for Virginia public data, with a command-line interface and an
MCP server for AI assistants. For policy researchers and developers building
applications for Virginia residents.

[Try the browser demos](https://pranava0x0.github.io/Commonwealth-MCP/demos.html)
· [Search the tools](https://pranava0x0.github.io/Commonwealth-MCP/tools.html)
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
the government services. See [examples/](examples/README.md) for other workflows, including
[a meeting-to-vote example](examples/trace_a_local_vote.py).

On Windows, virtual-environment executables live under `.venv\Scripts\`.

To point an AI client at the server, let the CLI write the config:

```bash
.venv/bin/commonwealth configure claude-code   # or claude, cursor, vscode, codex
```

It fills in the absolute path to this checkout. Add `--dry-run` to see the
change without making it.

### Without a checkout

The source manifests, the jurisdiction table and the skills ship inside the
package, so a wheel works on its own:

```bash
uv tool install commonwealth-mcp       # once it is published; see issue #40
commonwealth doctor
commonwealth skills list               # where the bundled skills are on disk
```

`uv tool install` puts the command on your PATH with its own environment.
`uv pip install` would refuse here, because it installs into a virtual
environment and this path has none.

The examples, the recorded fixtures and the tests are repo-only.

### Server and skills in one install

`plugins/commonwealth-mcp/` is a plugin bundle: the server entry and the
workflow skills together. In a client that reads a marketplace:

```
/plugin marketplace add pranava0x0/Commonwealth-MCP
/plugin install commonwealth-mcp@commonwealth-mcp
```

Install the package first, so `commonwealth serve` is on the path. For a
client with no plugin system, `commonwealth configure <client>` writes the
server entry. Clients with MCP prompt support can list and open each
workflow directly. For file-based discovery, copy a directory printed by
`commonwealth skills list` into the client’s skills folder.

## What works

| Question | Registered sources |
|---|---|
| Which government covers a place? | Names, FIPS codes, addresses, ZIP codes and coordinates; the table contains 133 counties and independent cities and 189 towns |
| What parcel is here? | Fairfax County, Loudoun County, Richmond City, Charles City County, the Town of Leesburg, and VGIN statewide parcels |
| How is a parcel zoned? | Fairfax, Loudoun and Roanoke counties, Richmond and Winchester cities, and the towns of Leesburg and Vienna. In Winchester the city publishes base districts; overlays are separate. A point in Vienna returns the town's layer and the county's, both unranked |
| Which address points, buildings, roads or public places are nearby? | VGIN statewide layers; VDOT road routes |
| Which water-quality stations are nearby? | DEQ monitoring stations, including historical stations |
| Where is a government boundary? | VGIN locality and town polygons |
| What does a Code of Virginia section say? | Section lookup by citation |
| Which part of the Code covers this subject? | The Code's own table of contents: titles, chapters, sections. A walk to a citation, not a full-text search — no public endpoint offers one |
| When does a local government meet? | Richmond City, Alexandria City, Albemarle County, Hampton City and Petersburg City, from the agenda platform each publishes through. The platform has no cancellation field, so a cancellation is read from the publisher's comment and labelled as a reading |
| What was on a meeting agenda, and how did members vote? | Richmond City and Alexandria City publish structured agenda items and individual vote records. An empty vote list does not establish how anyone voted |
| Where are the hospitals and urgent care? | Loudoun County's own map of them — a county's list, not a state licensing register, with no hours or services |

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

For a client used only for meeting and Code research, configure the civic
server. The geo server includes parcels, zoning and other spatial tools:

```bash
commonwealth configure claude-code --profile civic
commonwealth configure claude-code --profile geo
```

For legislative, election, purchase-order, flood-map and discharge-permit
records, add a third server:

```bash
commonwealth configure claude-code --profile records
```

Each named server has registry discovery and its own stdio launch command:
`commonwealth-civic`, `commonwealth-geo`, or `commonwealth-records`.
The existing `all` profile combines geo and civic. Add the records profile
alongside it to reach all 25 distinct tools.

| Lookup | Tool | What the publisher supplies |
| --- | --- | --- |
| Norfolk base zoning | `geo.find_zoning` | A city zoning district at a point. It does not determine permitted uses. |
| Flood map | `records.find_flood_zones` | Mapped zones and effective panels at a point, or intersecting a parcel where a polygon source is registered. An empty map does not establish low risk. |
| Discharge permits | `records.find_permit_outfalls` | DEQ outfall locations, permits and facilities within a radius of 1–10,000 metres. These are not violations or pollution measurements. |
| Legislative bills | `records.get_bill` | A bill in a named LIS session, its dated text identifiers, latest actions and paged history. |
| Legislative roll calls | `records.get_bill_votes` | A recorded vote joined to the bill and history reference, with member IDs, names where published and original vote codes. |
| Historical elections | `records.get_election_results` | Published locality rows for an exact date and one of eight offices. Candidate rows and the publisher’s summary rows must not be added together. No live election calls. |
| State purchases | `records.search_purchases` | FY2025 eVA order lines by exact vendor, agency or order number. Ordered amounts are not proof of payment. |

For example, call `records.get_bill` with `{"session":"20251","bill":"HB1600"}`.
Pass a returned `History_refid` as `history_ref` to `records.get_bill_votes`
with the same session and bill. Action `2518627` has 100 member positions;
follow `next_offset` until it is null. For order lines, try
`{"order":"A204_Z0081911"}`. The [recorded examples](docs/demos.html)
include all six new records tools. To refresh an example from its publisher,
use `commonwealth sources sample SOURCE_ID` from a checkout. The
[source inventory](THIRD_PARTY_DATA.yml) lists the publisher and terms for each fixture.

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

Directly integrated local sources cover a handful of places: Fairfax,
Loudoun, Roanoke and Charles City counties, Richmond and Winchester cities, and the Towns of Leesburg
and Vienna for parcels and zoning, and five localities for public
meetings. Adding another locality's layer is the most useful contribution
and the best-documented path ([CONTRIBUTING.md](CONTRIBUTING.md)); the
state's open-data portal lists many of them. Run
`commonwealth sources discover "zoning"` to find candidate publisher services.

Packaging landed on 2026-09-08: the source manifests, the jurisdiction
table and the skills ship inside the wheel, so an install works without a
checkout. What remains before the server is published is a release version
and the upload itself
([issue #40](https://github.com/pranava0x0/Commonwealth-MCP/issues/40)).
State legislation and full-text Code search are tracked in
[issue #11](https://github.com/pranava0x0/Commonwealth-MCP/issues/11) and
[issue #12](https://github.com/pranava0x0/Commonwealth-MCP/issues/12). The
legislature publishes bills and votes as keyless bulk files
([design/source-quirks.md § 20](design/source-quirks.md)), so #11 waits on
an adapter rather than a key. #12 waits on the publisher, whose search
backend reports itself down.

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
| `plugins/commonwealth-mcp/` | The plugin bundle: the server entry, the client manifests, and `skills/` — instructions for multi-tool workflows |
| `tests/`, `evals/` | Offline tests and workflow evaluations |
| [docs/](docs/README.md) | Published site and audit records |
| [research/](research/README.md) | Historical research; verify dated claims before reuse |

## License

Code: Apache-2.0. Registry: CC0. Documentation prose: CC-BY-4.0.
Recorded government responses retain their publishers' terms. See
[NOTICE](NOTICE) and [THIRD_PARTY_DATA.yml](THIRD_PARTY_DATA.yml).
