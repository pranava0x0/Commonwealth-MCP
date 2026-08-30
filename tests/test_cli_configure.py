"""`commonwealth configure` (GitHub issue #29, design/cli.md § 1).

The two properties the spec asks for are the ones worth testing: the
command converges when re-run, and it never touches a server entry it did
not write. A configure command that clobbers a neighbouring entry does more
damage than not existing.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from commonwealth.cli import configure as cfg

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "commonwealth.cli", "configure", *args],
        capture_output=True, text=True, cwd=cwd,
        env={"PATH": "/usr/bin:/bin", "HOME": str(cwd),
             "PYTHONPATH": str(ROOT / "src")})


def test_writes_a_config_for_a_fresh_project(tmp_path):
    out = _run("claude-code", "--path", str(tmp_path / ".mcp.json"),
               cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    doc = json.loads((tmp_path / ".mcp.json").read_text())
    entry = doc["mcpServers"]["commonwealth"]
    assert entry["args"][-2:] == ["--profile", "default"]


def test_running_twice_changes_nothing(tmp_path):
    """Idempotent, in the spec's sense: the second run converges rather
    than appending, duplicating, or reformatting."""
    target = tmp_path / ".mcp.json"
    _run("claude-code", "--path", str(target), cwd=tmp_path)
    first = target.read_text()
    second = _run("claude-code", "--path", str(target), cwd=tmp_path)
    assert target.read_text() == first
    assert "nothing to do" in second.stdout


def test_other_servers_are_left_alone(tmp_path):
    """The file belongs to the user's client, not to this project. An
    unrelated server and an unrelated top-level key both survive."""
    target = tmp_path / ".mcp.json"
    target.write_text(json.dumps({
        "mcpServers": {"github": {"command": "gh-mcp", "args": ["--stdio"]}},
        "somethingElse": {"keep": "me"},
    }))
    out = _run("claude-code", "--path", str(target), cwd=tmp_path)
    doc = json.loads(target.read_text())
    assert doc["mcpServers"]["github"] == {"command": "gh-mcp",
                                           "args": ["--stdio"]}
    assert doc["somethingElse"] == {"keep": "me"}
    assert "commonwealth" in doc["mcpServers"]
    assert "left alone: github" in out.stdout


def test_changing_the_profile_replaces_rather_than_appends(tmp_path):
    target = tmp_path / ".mcp.json"
    _run("claude-code", "--path", str(target), cwd=tmp_path)
    _run("claude-code", "--profile", "discovery", "--path", str(target),
         cwd=tmp_path)
    servers = json.loads(target.read_text())["mcpServers"]
    assert list(servers) == ["commonwealth"]
    assert servers["commonwealth"]["args"][-1] == "discovery"


def test_dry_run_prints_the_diff_and_writes_nothing(tmp_path):
    target = tmp_path / ".mcp.json"
    out = _run("claude-code", "--dry-run", "--path", str(target),
               cwd=tmp_path)
    assert out.returncode == 0
    assert not target.exists(), "--dry-run wrote the file"
    assert "commonwealth" in out.stdout
    assert "+" in out.stdout, "no diff was shown"


def test_a_broken_config_stops_the_command(tmp_path):
    """Rewriting an unparseable file would discard whatever the user had,
    and the parse error is the thing they need to see."""
    target = tmp_path / ".mcp.json"
    target.write_text("{ this is not json ")
    out = _run("claude-code", "--path", str(target), cwd=tmp_path)
    assert out.returncode == 1
    assert "not valid JSON" in out.stderr
    assert target.read_text() == "{ this is not json ", "overwrote it anyway"


def test_an_unknown_client_lists_the_known_ones(tmp_path):
    out = _run("emacs", "--path", str(tmp_path / "x.json"), cwd=tmp_path)
    assert out.returncode == 2
    assert "unknown client" in out.stderr
    for name in ("claude-code", "codex", "cursor", "vscode"):
        assert name in out.stderr


def test_a_toml_client_gets_a_block_to_paste(tmp_path):
    """The standard library reads TOML and does not write it, and a
    hand-rolled writer would reformat somebody else's config."""
    out = _run("codex", "--profile", "discovery", cwd=tmp_path)
    assert out.returncode == 0
    assert "[mcp_servers.commonwealth]" in out.stdout
    assert '"discovery"' in out.stdout


def test_vscode_uses_its_own_block_name():
    """VS Code names the block `servers`; the others use `mcpServers`. A
    single hardcoded key would silently produce a config VS Code ignores."""
    assert cfg.CLIENTS["vscode"].key == "servers"
    assert cfg.CLIENTS["claude-code"].key == "mcpServers"
    merged = cfg.merged({}, cfg.CLIENTS["vscode"], "default")
    assert "servers" in merged and "mcpServers" not in merged


@pytest.mark.parametrize("platform,expected", [
    ("darwin", "Library/Application Support/Claude"),
    ("linux", ".config/Claude"),
])
def test_desktop_config_path_follows_the_platform(monkeypatch, platform,
                                                  expected):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr("os.name", "posix")
    assert expected in str(cfg.desktop_config_path())


def test_every_client_the_help_names_is_handled():
    """The help string and the dispatch table drift apart otherwise, and
    the failure is a user typing a name the help offered."""
    named = {"claude", "claude-code", "codex", "cursor", "vscode"}
    assert named == set(cfg.CLIENTS) | cfg.TOML_CLIENTS


def test_an_installed_console_script_is_used_when_one_is_on_path(tmp_path):
    """The branch real users hit.

    Every other test here runs with a PATH that has no `commonwealth` on
    it, so they all take the sys.executable fallback and the console-script
    branch shipped untested.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "commonwealth"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)

    target = tmp_path / ".mcp.json"
    out = subprocess.run(
        [sys.executable, "-m", "commonwealth.cli", "configure",
         "claude-code", "--path", str(target)],
        capture_output=True, text=True, cwd=tmp_path,
        env={"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path),
             "PYTHONPATH": str(ROOT / "src")})
    assert out.returncode == 0, out.stderr

    entry = json.loads(target.read_text())["mcpServers"]["commonwealth"]
    assert entry["command"] == str(script), entry
    # No `-m commonwealth.cli` in front of the subcommand when the console
    # script carries its own environment.
    assert entry["args"] == ["serve", "--profile", "default"], entry


def test_an_unknown_profile_is_refused_before_anything_is_written(tmp_path):
    """A typo was accepted, written into the client config, and only
    rejected later by expand_profile — at which point the server would not
    start and the config on disk was already wrong."""
    target = tmp_path / ".mcp.json"
    out = _run("claude-code", "--profile", "defualt", "--path", str(target),
               cwd=tmp_path)
    assert out.returncode == 2
    assert "unknown profile" in out.stderr
    assert "default" in out.stderr
    assert not target.exists(), "wrote a config for an unknown profile"


def test_an_unknown_profile_is_refused_for_toml_clients_too(tmp_path):
    """The TOML branch returns before the client lookup, so it needs its
    own check or it prints a block naming a profile that cannot start."""
    out = _run("codex", "--profile", "defualt", cwd=tmp_path)
    assert out.returncode == 2
    assert "unknown profile" in out.stderr


def test_a_non_object_servers_block_is_refused(tmp_path):
    """read_config validated the top level only, so this reached dict()
    and produced a raw ValueError traceback."""
    target = tmp_path / ".mcp.json"
    target.write_text(json.dumps({"mcpServers": "oops"}))
    out = _run("claude-code", "--path", str(target), cwd=tmp_path)
    assert out.returncode == 1
    assert "where an object of server entries belongs" in out.stderr
    assert "Traceback" not in out.stderr
    assert json.loads(target.read_text()) == {"mcpServers": "oops"}
