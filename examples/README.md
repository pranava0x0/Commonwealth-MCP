# Runnable examples

Five short scripts, each a real question with a printed answer. They exist
because the quickest way to judge whether a tool is worth adopting is to
run something with it, and the alternative was reading the CLI reference
and composing a call.

Every one runs two ways:

```bash
python examples/whose_government.py            # recorded responses, no network
python examples/whose_government.py --live     # the real government services
```

Recorded is the default so a first run cannot fail on a network, a
firewall, or a government service being down at the wrong moment. The
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
| [one_address_every_question.py](one_address_every_question.py) | Everything the server knows about one address in Sterling, and the three different kinds of answer it gets back |

## If a script fails on a request it has no recording for

That is the expected failure when you edit one to ask something new. Run
it with `--live`, or record the exchange:

```bash
commonwealth sources sample <source-id>
```
