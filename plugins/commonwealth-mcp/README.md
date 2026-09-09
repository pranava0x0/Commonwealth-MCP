# The Commonwealth-MCP plugin bundle

One install that registers the MCP server and the workflow skills that use
it. Without this, a person copies each skill directory into their client's
skills folder by hand and wires the server separately.

```
plugins/commonwealth-mcp/
├── .mcp.json                    the server entry Codex reads
├── .mcp.claude.json             the same server, launched through the script
├── run-server.sh                finds the executable when PATH has not got it
├── .claude-plugin/plugin.json   Claude Code's manifest
├── .codex-plugin/plugin.json    Codex's manifest, with three starter prompts
└── skills/                      one SKILL.md per workflow
```

Two server entries because the two clients reach a bundled file
differently. Codex takes the command off the path, the way the reference
plugin this was modelled on does. Claude Code expands
`${CLAUDE_PLUGIN_ROOT}` inside a manifest, so its entry runs
`run-server.sh`, which finds the server in a checkout, a tool install, or
a bare clone. A test asserts the two launch the same profile; a client
that read both would otherwise get two different tool lists.

The profile is `all`, and that is a requirement rather than a preference:
the bundle carries six skills, and three of them walk tools the `default`
profile leaves out. A test derives the needed tools from each skill's own
frontmatter, so adding a skill that needs more fails until the profile
covers it.

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

Each of these has a test in `tests/test_plugin_bundle.py`:

- Every skill under `skills/` is reachable from the path the manifests
  declare. A skill that is on disk and not in the bundle would ship to
  nobody.
- Both manifests name the same server, the same subcommand, and the same
  version as `pyproject.toml`.
- The Codex manifest's starter prompts are the three the site's quick start
  shows, which are themselves filled in from calls on the recorded trail.
  A prompt naming a parcel the demo no longer queries fails the test.
- The tool count the site prints is the one the bundled profile expands to.

## One thing to know before installing

The Codex marketplace entry declares `"authentication": "ON_INSTALL"`,
copied from the reference plugin because that is the only value seen in a
manifest known to load. This server reads published records and takes no
key, no account and no token, so there is nothing for that step to
collect. If Codex asks for a credential on install, that declaration is
why, and skipping it costs nothing.
