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
    """../design/architecture.md decision 0011: recorded third-party payloads carry source+rights."""
    fixture_files = sorted((ROOT / "tests" / "fixtures" / "sources")
                           .rglob("recorded.json"))
    assert fixture_files, "no recorded fixtures found"
    for f in fixture_files:
        doc = json.loads(f.read_text())
        assert doc["rights"]["terms_url"], f
        assert doc["rights"]["publisher"], f
        assert doc["recorded_at"], f
    print(f"rights metadata checked on {len(fixture_files)} fixture file(s)")


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
