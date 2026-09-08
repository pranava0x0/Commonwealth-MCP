# Runnable examples

Install from the [project README](../README.md#start-here), then run from
the checkout root. Start with `one_address_every_question.py`.

Every one runs two ways:

```bash
.venv/bin/python examples/whose_government.py            # recorded responses, no network
.venv/bin/python examples/whose_government.py --live     # the real government services
```

Recorded mode makes no network requests. The
recordings under `tests/fixtures/sources/` were written by `commonwealth
sources sample` against the live services; nothing here is synthesized.

Each script prints the same five coverage dimensions, sources, and
warnings the MCP tools return. An empty answer means something
different depending on which dimension says why, so the dimensions are
printed even when the answer is a hit.

| Script | The question |
|---|---|
| [whose_government.py](whose_government.py) | Which government covers a mailing address, an ambiguous name, and a ZIP that crosses boundaries? |
| [screen_a_parcel.py](screen_a_parcel.py) | Who governs this parcel, how is it zoned, what is built on it, what is monitored nearby? |
| [what_is_covered.py](what_is_covered.py) | What does this project cover, and what does an empty answer mean here? |
| [two_sources_disagree.py](two_sources_disagree.py) | What happens when two official sources describe the same road differently? |
| [one_address_every_question.py](one_address_every_question.py) | Parcel, zoning and nearby-feature queries for one address in Sterling |
| [two_governments_one_ground.py](two_governments_one_ground.py) | One point in the Town of Vienna: the town's zoning layer and the county's both answer, and a parcel number is read over the county's polygon |

## If a script fails on a request it has no recording for

That is the expected failure when you edit one to ask something new. Run
it with `--live`, or record the exchange:

```bash
commonwealth sources sample <source-id>
```
