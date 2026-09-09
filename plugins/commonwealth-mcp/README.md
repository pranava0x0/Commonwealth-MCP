# The Commonwealth-MCP plugin bundle

One install that registers the MCP server and the workflow skills that use
it. Without this, a person copies each skill directory into their client's
skills folder by hand and wires the server separately.

```
plugins/commonwealth-mcp/
├── .mcp.json                    the server entry, one stdio server
├── .claude-plugin/plugin.json   Claude Code's manifest
├── .codex-plugin/plugin.json    Codex's manifest, with three starter prompts
└── skills/                      one SKILL.md per workflow
```

`skills/` is the only copy in the repo. `pyproject.toml` force-includes this
directory into the wheel at `commonwealth/_data/skills`, so an installed
server finds the same files, and `commonwealth skills list` prints whichever
copy is in use.

## Installing it

Install the package first, so `commonwealth serve` is on the path — the
[quick start](https://pranava0x0.github.io/Commonwealth-MCP/#quick-start)
has the four steps. Then, in Claude Code:

```
/plugin marketplace add pranava0x0/Commonwealth-MCP
/plugin install commonwealth-mcp@commonwealth-mcp
```

For a client with no plugin system, `commonwealth configure <client>` writes
the server entry on its own and fills in the absolute path to the checkout.
That path installs no skills.

## What the manifests must agree about

Three things, each with a test in `tests/test_plugin_bundle.py`:

- Every skill under `skills/` is reachable from the path the manifests
  declare. A skill that is on disk and not in the bundle would ship to
  nobody.
- Both manifests name the same server, the same subcommand, and the same
  version as `pyproject.toml`.
- The Codex manifest's starter prompts are the three the site's quick start
  shows, which are themselves filled in from calls on the recorded trail.
  A prompt naming a parcel the demo no longer queries fails the test.
