"""Repo-wide invariants: derivation over hand-typed lists, import boundaries,
profile ceilings, alias wiring. The counts print so a vacuous pass is visible."""
import ast
import json
import sys
from pathlib import Path

import pytest

from commonwealth.core import toolreg
from commonwealth.servers.build import registries

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "commonwealth"


def test_core_imports_no_framework_or_upper_layers():
    """../design/architecture.md decision 0003+0015: core stays import-clean of mcp/servers/cli."""
    offenders = []
    files = sorted((SRC / "core").rglob("*.py"))
    assert files, "core package vanished?"
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [("." * node.level) + node.module]
            for name in names:
                if name.split(".")[0] == "mcp" or ".servers" in name \
                        or ".cli" in name or "adapters" in name:
                    offenders.append(f"{path.name}: {name}")
    assert offenders == [], offenders
    print(f"core import boundary checked over {len(files)} files")


def test_domains_import_no_mcp():
    files = sorted((SRC / "domains").rglob("*.py"))
    offenders = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                offenders += [f"{path.name}: {a.name}" for a in node.names
                              if a.name.split(".")[0] == "mcp"]
            elif isinstance(node, ast.ImportFrom) and node.module \
                    and node.module.split(".")[0] == "mcp":
                offenders.append(f"{path.name}: {node.module}")
    assert offenders == [], offenders
    print(f"domain import boundary checked over {len(files)} files")


def test_every_domain_package_has_the_four_test_tiers():
    """design/testing-and-demos.md § 1, derived from the live registry —
    never a hand-typed package list."""
    packages = sorted(registries())
    assert packages, "no domain registries — derivation basis vanished"
    name_map = {"registry": "registry_tools"}
    missing = []
    for pkg in packages:
        dirname = name_map.get(pkg, pkg)
        d = ROOT / "tests" / "servers" / dirname
        for tier in ("contract", "unit", "resilience", "security"):
            if not (d / f"test_{dirname}_{tier}.py").exists() and \
               not (d / f"test_{pkg}_{tier}.py").exists():
                missing.append(f"{dirname}/{tier}")
    assert missing == [], f"missing test tiers: {missing}"
    print(f"test-tier layout checked for {len(packages)} domain packages")


def test_profiles_expand_within_ceilings_and_all_toolsets_exist():
    regs = registries()
    for profile in toolreg.PROFILES:
        specs = toolreg.expand_profile(profile, regs)
        assert len(specs) <= toolreg.PROFILE_HARD_CEILING
        if profile == "default":
            assert len(specs) <= toolreg.PROFILE_DEFAULT_CEILING
        print(f"profile {profile}: {len(specs)} tools")


def test_the_ceilings_refuse_at_expansion_not_only_in_ci(monkeypatch):
    """GitHub issue #22. `PROFILE_DEFAULT_CEILING` was defined and never
    read at runtime, so an oversized default failed CI rather than
    refusing to start — the claim the ceiling makes was false at runtime
    while CI reported success. Mutation-checked, because a constant that
    nothing reads passes every test that only reads it too."""
    import pytest

    regs = registries()
    monkeypatch.setattr(toolreg, "PROFILE_DEFAULT_CEILING", 2)
    with pytest.raises(ValueError) as err:
        toolreg.expand_profile("default", regs)
    assert "ceiling of 2" in str(err.value)

    monkeypatch.setattr(toolreg, "PROFILE_DEFAULT_CEILING", 12)
    monkeypatch.setattr(toolreg, "PROFILE_HARD_CEILING", 3)
    with pytest.raises(ValueError) as err:
        toolreg.expand_profile("all", regs)
    assert "ceiling of 3" in str(err.value)


def test_the_floor_warns_and_starts_rather_than_refusing(monkeypatch, caplog):
    """The other half of #22, decided the other way: a hard floor would
    refuse to start the server that exists whenever a domain is still
    being built."""
    import logging

    regs = registries()
    monkeypatch.setattr(toolreg, "PROFILE_FLOOR", 99)
    with caplog.at_level(logging.WARNING, logger="commonwealth.toolreg"):
        specs = toolreg.expand_profile("default", regs)
    assert specs, "the profile still expands"
    assert "under decision 0002's floor" in caplog.text


def test_the_default_profile_is_inside_the_0002_band():
    """0002 chose 8-12 for a default profile. `default` was five tools
    when #22 was written and is the shape the amendment describes now."""
    specs = toolreg.expand_profile("default", registries())
    assert toolreg.PROFILE_FLOOR <= len(specs) <= \
        toolreg.PROFILE_DEFAULT_CEILING, [s.name for s in specs]


def test_one_registry_tool_is_in_default_and_the_meta_tools_are_not():
    """Decision 0001's 2026-08-29 amendment (GitHub issue #21):
    resolve_jurisdiction answers a question about Virginia and ships in
    `default`; the three that answer questions about the registry itself
    stay in `discovery`."""
    names = {s.name for s in toolreg.expand_profile("default", registries())}
    assert "registry.resolve_jurisdiction" in names
    assert not (names & {"registry.search_sources",
                         "registry.describe_source",
                         "registry.source_status"})


def test_alias_mechanism_fires_when_given_an_alias(monkeypatch):
    """The table is empty by design; prove the mechanism works by injecting
    a fake alias and watching it resolve and register."""
    assert toolreg.DEPRECATED_TOOL_ALIASES == {}, (
        "table gained a real entry — update this test's expectations "
        "deliberately")
    monkeypatch.setitem(toolreg.DEPRECATED_TOOL_ALIASES,
                        "geo.zoning_lookup_old", "geo.find_zoning")
    assert toolreg.resolve_alias("geo.zoning_lookup_old") == "geo.find_zoning"

    from commonwealth.servers.build import build_server
    from tests.conftest import build_ctx
    server = build_server(build_ctx(), profile="all")

    import anyio
    from mcp.client import Client

    async def names():
        async with Client(server) as client:
            return [t.name for t in (await client.list_tools()).tools]

    tool_names = anyio.run(names)
    assert "geo.zoning_lookup_old" in tool_names, (
        "alias did not register as a callable tool")


def test_capability_vocab_is_the_single_source_of_truth():
    """Every capability a manifest declares or a tool selects against must
    exist in capabilities.yaml — greppable derivation, not convention."""
    import yaml
    vocab_doc = yaml.safe_load((ROOT / "sources" / "capabilities.yaml")
                               .read_text())
    vocab = {c["id"] for c in vocab_doc["capabilities"]}
    src_text = "\n".join(p.read_text()
                         for p in (SRC / "domains").rglob("*.py"))
    import re
    used = set(re.findall(r'select\(\s*"([a-z_.]+)"', src_text))
    used |= set(re.findall(r'unavailable_for\(\s*"([a-z_.]+)"', src_text))
    assert used, "no capability selections found — the grep basis broke"
    unknown = used - vocab
    assert unknown == set(), f"tools select capabilities not in the vocab: "\
                             f"{unknown}"
    print(f"capability derivation: {len(used)} used / {len(vocab)} in vocab")


def test_committed_fixture_carries_rights_metadata():
    """../design/architecture.md decision 0011: recorded third-party payloads carry source+rights.

    Every publisher whose responses are in the file, not only the one the
    directory is named for: a zoning-only source records its county's and
    the state's answers for the same point, and naming one publisher would
    put the other two under terms that are not theirs.
    """
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "src"))
    from commonwealth.cli.__main__ import contributing_sources
    from commonwealth.runtime import load_context

    ctx = load_context()
    fixture_files = sorted((ROOT / "tests" / "fixtures" / "sources")
                           .rglob("recorded.json"))
    assert fixture_files, "no recorded fixtures found"
    multi = 0
    for f in fixture_files:
        doc = json.loads(f.read_text())
        assert doc["recorded_at"], f
        listed = doc["rights"]["sources"]
        assert listed, f
        for entry in listed:
            assert entry["source_id"], f
            assert entry["publisher"], f
            assert entry["terms_url"], f
        assert listed[0]["source_id"] == doc["source_id"], (
            f"{f}: the recording source is listed first")
        manifest = ctx.sources.get(doc["source_id"])
        assert manifest is not None, f
        expected = [c.id for c in contributing_sources(
            manifest, doc["exchanges"], ctx)]
        assert [e["source_id"] for e in listed] == expected, (
            f"{f}: the rights block does not match the publishers whose "
            f"services actually answered into it")
        multi += len(listed) > 1
    assert multi, ("no committed fixture is cross-source any more; this "
                   "test would pass vacuously on the case it exists for")
    print(f"rights metadata checked on {len(fixture_files)} fixture file(s), "
          f"{multi} of them cross-source")


def test_the_wheel_carries_the_data_the_runtime_reads():
    """A wheel installed outside a checkout has no repo root above it.

    Every command died at startup on a missing capability vocabulary
    until `sources/` and `skills/` were force-included into the package.
    The two halves are `runtime._data_root()` and pyproject's
    `force-include` block, and this asserts they still name the same
    directories — a data directory added to one and not the other ships a
    wheel that fails on the machine it was meant for.
    """
    import tomllib

    from commonwealth import runtime

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    included = (pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
                ["force-include"])
    for name in ("sources", "skills"):
        assert included.get(name) == f"commonwealth/_data/{name}", (
            f"{name}/ is read at runtime and is not force-included into "
            "the wheel; an installed server would not find it")
        assert (ROOT / name).is_dir(), f"{name}/ is force-included and gone"

    # And the runtime looks for them under one root, so a checkout and a
    # wheel differ in that root and in nothing else.
    assert runtime.SOURCES_DIR == runtime.DATA_ROOT / "sources"
    assert runtime.SKILLS_DIR == runtime.DATA_ROOT / "skills"
    assert runtime.DATA_ROOT == ROOT, (
        "run from a checkout, the data root is the repo root")

    # And it stays the repo root even though `pip install -e .` also
    # materialises the bundled copy into site-packages. That copy is
    # frozen at install time, so preferring it would serve a developer
    # the manifests they had when they last installed.
    stale = Path(runtime.__file__).resolve().parent / "_data"
    assert runtime._data_root() == ROOT, (
        f"a checkout must win over a bundled copy at {stale}")


def _semver_of(pep440: str) -> str:
    """The SemVer spelling of a PEP 440 version.

    Only the forms this project releases: `X.Y.Z`, and a prerelease
    suffix `devN`, `aN`, `bN` or `rcN`, which SemVer writes after a
    hyphen with a dot before the number. Anything else raises rather than
    guessing, because a wrong conversion here publishes a version nobody
    can install.
    """
    import re

    m = re.fullmatch(r"(\d+\.\d+\.\d+)(?:\.?(dev|a|b|rc)(\d+))?", pep440)
    if m is None:
        raise AssertionError(
            f"{pep440!r} is not a version shape this converter knows; "
            "extend it deliberately rather than publishing a guess")
    release, kind, number = m.groups()
    return release if kind is None else f"{release}-{kind}.{number}"


def test_the_pep440_to_semver_conversion_is_the_one_the_registry_wants():
    assert _semver_of("0.1.0") == "0.1.0"
    assert _semver_of("0.1.0.dev0") == "0.1.0-dev.0"
    assert _semver_of("1.2.3rc1") == "1.2.3-rc.1"
    assert _semver_of("2.0.0b2") == "2.0.0-b.2"
    with pytest.raises(AssertionError):
        _semver_of("0.1")


def test_the_registry_entry_matches_the_package_it_names():
    """`server.json` is what the MCP registry publishes (issue #40).

    Its name, version and entry point are a second copy of what
    pyproject declares. A published listing whose install line names a
    version that was never released, or an executable the package does
    not install, is worse than no listing.
    """
    import json
    import tomllib

    entry = json.loads((ROOT / "server.json").read_text())
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project = pyproject["project"]

    package = entry["packages"][0]
    assert package["identifier"] == project["name"], (
        "the registry entry names a different PyPI package")
    # Two version strings for one release, because the two systems spell
    # a prerelease differently: the registry's schema wants SemVer and
    # PyPI wants PEP 440. `0.1.0.dev0` is not a SemVer string and the
    # registry rejects the entry before it ever reaches the package, so
    # the top-level version is converted and the package's is verbatim.
    assert package["version"] == project["version"], (
        "the package entry must name the version PyPI actually has")
    assert entry["version"] == _semver_of(project["version"]), (
        f"server.json says {entry['version']}, and {project['version']} "
        f"converts to {_semver_of(project['version'])}")
    assert package["transport"]["type"] == "stdio", (
        "the server speaks stdio and the listing must say so")

    # `uvx <package>` runs an executable named after the package, so the
    # package has to install one.
    assert project["name"] in project["scripts"], (
        f"the listing runs `uvx {project['name']}` and the package "
        f"installs no {project['name']!r} executable")
    argv = [a["value"] for a in package.get("packageArguments", [])]
    assert argv == ["serve"], (
        f"the listing would run the CLI with {argv}, which is not the "
        "server")


def test_third_party_data_inventory_is_current():
    """GitHub issue #24 / decision 0011. THIRD_PARTY_DATA.yml records whose
    terms each recorded fixture is under. A stale copy would misstate
    somebody's licensing, so it is generated and checked rather than
    hand-maintained."""
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_third_party_data.py"),
         "--check"],
        capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    print(proc.stdout.strip())


def test_the_license_set_decision_0011_chose_exists():
    """The repo was public with only a pyproject line, which covers the
    Python package metadata and nothing else."""
    missing = [name for name in (
        "LICENSE", "NOTICE", "THIRD_PARTY_DATA.yml",
        "sources/LICENSE", "docs/LICENSE-DOCS",
    ) if not (ROOT / name).exists()]
    assert missing == [], f"missing license files: {missing}"
    assert "Apache License" in (ROOT / "LICENSE").read_text()[:200]
    assert "CC0" in (ROOT / "sources" / "LICENSE").read_text()
    print("license set present: 5 files")


def test_the_governance_prerequisites_for_outside_contributions_exist():
    """design/security-and-data-handling.md § 5 lists what has to exist
    before the first source manifest arrives from outside the project
    (#35). Four of the five were missing until 2026-09-01, and a registry
    listing (#40) is an open invitation, so they are pinned rather than
    remembered."""
    missing = [name for name in (
        "CONTRIBUTING.md",
        ".github/GOVERNANCE.md",
        ".github/SECURITY.md",
        ".github/CODEOWNERS",
    ) if not (ROOT / name).exists()]
    assert missing == [], f"missing governance files: {missing}"

    owners = (ROOT / ".github" / "CODEOWNERS").read_text()
    assert "/sources/" in owners, (
        "CODEOWNERS does not route sources/**, which is the one path § 5 "
        "names by name")

    contributing = (ROOT / "CONTRIBUTING.md").read_text()
    assert "Signed-off-by" in contributing, "the DCO note is gone"
    for link in (".github/SECURITY.md", ".github/GOVERNANCE.md"):
        assert link in contributing, (
            f"{link} exists but CONTRIBUTING does not send anyone to it")
