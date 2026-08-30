"""Write MCP client configuration (design/cli.md § 1, GitHub issue #29).

Pointing a client at this server otherwise means hand-editing JSON and
knowing which profile name to use. That is the first thing anyone does and
the least documented.

Two properties the spec asks for, and both are the whole point:

- **Idempotent.** Re-running converges on the same file. The existing
  config is parsed, this project's entry is replaced, and every other
  server the user configured is written back untouched. A configure
  command that clobbers a neighbouring entry is worse than no command.
- **`--dry-run` shows the exact diff** before anything is written. These
  files belong to the user's editor and assistant, not to this project.
"""
from __future__ import annotations

import difflib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

SERVER_KEY = "commonwealth"


@dataclass(frozen=True)
class Client:
    """Where a client keeps its MCP config, and under which key.

    `scope` says whose file it is. A "project" file lives in the repo the
    user is working in, so it is written relative to the working directory;
    a "user" file is global and lives under the home directory.
    """
    name: str
    key: str                    # top-level object holding server entries
    scope: str                  # "user" | "project"
    path: str                   # relative to home (user) or cwd (project)
    note: str = ""


# Only clients whose config file is JSON and whose location is stable are
# written. Codex uses TOML, and the standard library can read TOML but not
# write it; adding a writer dependency to emit six lines is not worth it,
# so that one prints a block to paste (see `render_toml_block`).
CLIENTS: dict[str, Client] = {
    "claude-code": Client(
        "claude-code", "mcpServers", "project", ".mcp.json",
        note="Project-scoped, so it is shared with anyone who clones the "
             "repo. Commit it or do not, as you prefer."),
    "cursor": Client(
        "cursor", "mcpServers", "project", ".cursor/mcp.json"),
    "vscode": Client(
        "vscode", "servers", "project", ".vscode/mcp.json",
        note="VS Code names the block `servers`, not `mcpServers`."),
    "claude": Client(
        "claude", "mcpServers", "user", "",
        note="Claude Desktop. The path differs per platform; see "
             "`desktop_config_path`."),
}

TOML_CLIENTS = {"codex"}


def desktop_config_path() -> Path:
    """Claude Desktop's config file, which is in a different place on each
    platform. Pass `--path` to override when it is somewhere else."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / \
            "claude_desktop_config.json"
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else home / "AppData" / "Roaming"
        return root / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def config_path(client: Client, override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    if client.name == "claude":
        return desktop_config_path()
    if client.scope == "user":
        return (Path.home() / client.path).resolve()
    return (Path.cwd() / client.path).resolve()


def launch_command() -> dict:
    """How the client should start the server.

    Prefer the installed console script, because it carries its own
    virtualenv and works whatever the client's cwd is. Without one on PATH,
    fall back to the interpreter running this code, for the same reason.
    """
    script = shutil.which("commonwealth")
    if script:
        return {"command": script, "args": []}
    return {"command": sys.executable, "args": ["-m", "commonwealth.cli"]}


def server_entry(profile: str) -> dict:
    launch = launch_command()
    return {
        "command": launch["command"],
        "args": [*launch["args"], "serve", "--profile", profile],
    }


def merged(existing: dict, client: Client, profile: str) -> dict:
    """This project's entry set, everything else preserved.

    A shallow copy per level rather than a mutation, so a caller comparing
    before and after sees two distinct documents.
    """
    out = dict(existing)
    servers = dict(out.get(client.key) or {})
    servers[SERVER_KEY] = server_entry(profile)
    out[client.key] = servers
    return out


def read_config(path: Path) -> tuple[dict, str]:
    """(parsed, raw text). A missing file is an empty config, not an error.

    A file that exists but does not parse stops the command. Rewriting it
    would discard whatever the user had, and the parse error is the thing
    they need to see.
    """
    if not path.exists():
        return {}, ""
    raw = path.read_text()
    if not raw.strip():
        return {}, raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as err:
        raise ValueError(
            f"{path} is not valid JSON ({err}). Fix or move it; refusing "
            "to overwrite a file that may hold configuration.") from err
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} holds a {type(parsed).__name__}, not an "
                         "object; refusing to overwrite it.")
    return parsed, raw


def render(config: dict) -> str:
    return json.dumps(config, indent=2) + "\n"


def diff(path: Path, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"{path} (current)", tofile=f"{path} (proposed)"))


def render_toml_block(profile: str) -> str:
    """The block to paste into a TOML client's config.

    Written out rather than merged into the file: the standard library
    reads TOML and does not write it, and a hand-rolled writer would
    reformat comments and ordering out of somebody else's config.
    """
    entry = server_entry(profile)
    args = ", ".join(json.dumps(a) for a in entry["args"])
    return (f'[mcp_servers.{SERVER_KEY}]\n'
            f'command = {json.dumps(entry["command"])}\n'
            f'args = [{args}]\n')
