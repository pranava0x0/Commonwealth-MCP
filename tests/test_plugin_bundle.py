"""The plugin bundle ships the server and its skills in one install.

Three manifests describe the same thing to three readers — Claude Code,
Codex, and the site's quick start — and each one is a place the description
can go stale. These assert they agree with each other and with the files
they point at.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "commonwealth-mcp"
SKILLS = PLUGIN / "skills"
CLAUDE_MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
CODEX_MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
MCP_JSON = PLUGIN / ".mcp.json"
CLAUDE_MARKET = ROOT / ".claude-plugin" / "marketplace.json"
CODEX_MARKET = ROOT / ".agents" / "plugins" / "marketplace.json"


def _load(path: Path) -> dict:
    assert path.exists(), f"missing {path.relative_to(ROOT)}"
    return json.loads(path.read_text())


@pytest.fixture(scope="module")
def claude() -> dict:
    return _load(CLAUDE_MANIFEST)


@pytest.fixture(scope="module")
def codex() -> dict:
    return _load(CODEX_MANIFEST)


def test_every_skill_on_disk_is_inside_the_bundle(codex):
    """A skill the bundle does not carry ships to nobody.

    Claude Code discovers a plugin's skills by convention, in `skills/`
    under the plugin root; Codex is told the path. Both have to find the
    same set, and it has to be every skill the repo has.
    """
    from commonwealth.core.skills import load_skills

    on_disk = sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))
    assert on_disk, "the bundle carries no skills"
    loaded = sorted(sk.name for sk in load_skills(SKILLS))
    assert loaded == on_disk, (
        "a SKILL.md under the bundle does not load; the loader and the "
        "directory disagree about what a skill is")

    declared = codex["skills"]
    assert declared.startswith("./"), \
        f"the Codex manifest's skills path {declared!r} must be plugin-relative"
    target = (PLUGIN / declared[2:]).resolve()
    assert target == SKILLS.resolve(), (
        f"the Codex manifest points at {declared}, which is not the "
        "directory the skills are in")
    # And Claude Code's convention: no key, the directory has to be there.
    assert SKILLS.is_dir()


def test_the_runtime_and_the_bundle_read_the_same_skills():
    """`commonwealth skills list` and the manifest must agree (issue #53).

    The runtime prefers a checkout over the copy inside an installed wheel,
    so in this repo it must be looking at the bundle's directory and not at
    a stale `skills/` left somewhere else.
    """
    from commonwealth import runtime
    from commonwealth.core.skills import load_skills

    assert runtime.SKILLS_DIR.resolve() == SKILLS.resolve(), (
        f"the runtime loads skills from {runtime.SKILLS_DIR}, and the "
        f"bundle ships {SKILLS}")
    assert not (ROOT / "skills").exists(), (
        "skills/ moved into the plugin bundle; a directory left at the old "
        "path is a second copy waiting to go stale")
    assert sorted(sk.name for sk in load_skills(runtime.SKILLS_DIR)) == \
        sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))


def test_the_wheel_force_includes_the_bundles_skills():
    """The wheel's copy comes from this directory, not another one."""
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    included = (pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
                ["force-include"])
    src = str(SKILLS.relative_to(ROOT))
    assert included.get(src) == "commonwealth/_data/skills", (
        f"{src} is what the runtime reads and it is not force-included "
        "into the wheel")


def test_the_server_entry_matches_what_configure_writes():
    """`.mcp.json` and `commonwealth configure` must launch the same server.

    They cannot be byte-identical: `configure` fills in the absolute path
    to a checkout's interpreter, and a manifest that shipped one machine's
    path would be useless on every other. What has to match is the server
    name, the subcommand, and the profile.
    """
    from commonwealth.cli import configure as cfg

    entry = _load(MCP_JSON)["mcpServers"]
    assert list(entry) == [cfg.SERVER_KEY], (
        f"the bundle registers {list(entry)} and configure writes "
        f"{cfg.SERVER_KEY!r}; a client that has both would run two servers "
        "under two names")
    args = entry[cfg.SERVER_KEY]["args"]
    profile = args[args.index("--profile") + 1]
    written = cfg.server_entry(profile)["args"]
    assert written[-3:] == args[-3:], (
        f"configure launches {written} and the bundle launches {args}; "
        "the subcommand and the profile have to be the same")


def test_both_marketplaces_list_the_plugin_at_its_real_path(claude):
    for market, key in ((CLAUDE_MARKET, "source"), (CODEX_MARKET, "path")):
        data = _load(market)
        listed = [p for p in data["plugins"] if p["name"] == claude["name"]]
        assert listed, (
            f"{market.relative_to(ROOT)} does not list {claude['name']}")
        rel = listed[0][key]
        assert (ROOT / rel).resolve() == PLUGIN.resolve(), (
            f"{market.relative_to(ROOT)} points {key} at {rel}, and the "
            f"plugin is at {PLUGIN.relative_to(ROOT)}")


def test_the_manifests_agree_with_each_other_and_with_the_package(claude,
                                                                  codex):
    import tomllib

    assert claude["name"] == codex["name"]
    assert claude["homepage"] == codex["homepage"]
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    release = pyproject["project"]["version"].partition(".dev")[0]
    for manifest, path in ((claude, CLAUDE_MANIFEST), (codex, CODEX_MANIFEST)):
        assert manifest["version"] == release, (
            f"{path.relative_to(ROOT)} says {manifest['version']} and the "
            f"package is {pyproject['project']['version']}")


def test_the_codex_prompts_are_the_ones_the_quick_start_shows():
    """Issue #53: the manifest's default prompts reuse the quick start's.

    Those are filled in from calls on the recorded trail, so a prompt here
    naming a parcel or a citation the demo no longer queries is a prompt
    whose answer a reader cannot go and read.
    """
    site = json.loads((ROOT / "docs" / "data" / "core.json").read_text())
    shown = [p["text"] for p in site["starter_prompts"]]
    assert _load(CODEX_MANIFEST)["prompts"] == shown, (
        "the Codex manifest's prompts and the site's quick start have "
        "drifted; regenerate the site and copy them across")


def test_the_site_names_the_marketplace_a_reader_would_type():
    """The install command on the page has to be the one that works."""
    site = json.loads((ROOT / "docs" / "data" / "core.json").read_text())
    plugin = site["plugin"]
    assert plugin["marketplace"] == "pranava0x0/Commonwealth-MCP"
    assert plugin["marketplace_name"] == _load(CLAUDE_MARKET)["name"]
    assert plugin["name"] == _load(CLAUDE_MANIFEST)["name"]
    assert plugin["skill_count"] == len(list(SKILLS.glob("*/SKILL.md")))
