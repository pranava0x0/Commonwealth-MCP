"""Tool registration: deterministic ordering, toolsets, deprecation aliases.

- Registration order IS the wire order (`tools/list` SHOULD be deterministic
  per the 2026-07-28 spec; a contract test asserts it).
- The alias table ships empty but wired (github-mcp-server's pattern, adopted
  by design/domain-servers.md § 1.6): renaming a tool means adding its old
  name here, and a test proves resolution works before it is ever needed.
- Profiles compose (package, toolset) selections; activating a profile that
  references a missing toolset fails at startup, loudly (design/hub-catalog.md § 2).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("commonwealth.toolreg")

# old-name -> current-name. Empty until the first rename; never delete rows.
DEPRECATED_TOOL_ALIASES: dict[str, str] = {}


def resolve_alias(name: str) -> str:
    return DEPRECATED_TOOL_ALIASES.get(name, name)


@dataclass(frozen=True)
class ToolSpec:
    name: str                     # e.g. "geo.find_zoning"
    description: str
    toolset: str                  # e.g. "default", "discovery", "spatial"
    contract_version: str
    fn: Callable[..., Awaitable[Any]]


@dataclass
class ToolRegistry:
    package: str                  # "geo" | "registry"
    _tools: list[ToolSpec] = field(default_factory=list)

    def register(self, spec: ToolSpec) -> ToolSpec:
        if any(t.name == spec.name for t in self._tools):
            raise ValueError(f"duplicate tool name {spec.name!r} in "
                             f"{self.package}")
        self._tools.append(spec)
        return spec

    def tools(self, toolset: str | None = None) -> list[ToolSpec]:
        if toolset is None or toolset == "*":
            return list(self._tools)
        out = [t for t in self._tools if t.toolset == toolset]
        if not out:
            raise ValueError(
                f"toolset {toolset!r} selects zero tools in package "
                f"{self.package!r}; known toolsets: "
                f"{sorted({t.toolset for t in self._tools})}")
        return out

    def toolsets(self) -> set[str]:
        return {t.toolset for t in self._tools}


# Profiles: ordered (package, toolset) pairs. Sized per ../../../design/architecture.md decision 0002
# (8-12 default, ceiling 20 — asserted by a contract test).
PROFILES: dict[str, list[tuple[str, str]]] = {
    "default": [("registry", "discovery-min"), ("geo", "default"),
                ("civic", "default")],
    "discovery": [("registry", "discovery-min"), ("registry", "discovery"),
                  ("geo", "default"), ("civic", "default")],
    "all": [("registry", "*"), ("geo", "*"), ("civic", "*")],
}

# ../../../design/architecture.md decision 0002, amended 2026-08-29 (GitHub
# issue #22). Both ceilings are enforced here, at expansion, so an
# oversized profile refuses to start rather than only failing CI. The
# floor is a WARNING, not a refusal: it describes a filled-out toolset,
# and a hard floor would refuse to start the server that exists whenever
# a domain is still being built. The amendment on 0002 records that
# split.
PROFILE_FLOOR = 8
PROFILE_DEFAULT_CEILING = 12
PROFILE_HARD_CEILING = 20


def expand_profile(profile: str,
                   registries: dict[str, ToolRegistry]) -> list[ToolSpec]:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; known: "
                         f"{sorted(PROFILES)}")
    out: list[ToolSpec] = []
    for package, toolset in PROFILES[profile]:
        reg = registries.get(package)
        if reg is None:
            raise ValueError(
                f"profile {profile!r} references package {package!r} which "
                "is not loaded — refusing to start with a silently smaller "
                "tool surface")
        out.extend(reg.tools(toolset))
    if len(out) > PROFILE_HARD_CEILING:
        raise ValueError(
            f"profile {profile!r} expands to {len(out)} tools, over the "
            f"../../../design/architecture.md decision 0002 ceiling of {PROFILE_HARD_CEILING}")
    if profile == "default" and len(out) > PROFILE_DEFAULT_CEILING:
        raise ValueError(
            f"the 'default' profile expands to {len(out)} tools, over "
            f"decision 0002's ceiling of {PROFILE_DEFAULT_CEILING} for it. "
            "A task profile may go to 20; the default one may not — the "
            "measured selection cliffs are what the number is for.")
    if len(out) < PROFILE_FLOOR:
        log.warning(
            "profile %r expands to %d tools, under decision 0002's floor "
            "of %d. The floor describes a filled-out toolset; this is a "
            "report that a domain is still being built, not a fault.",
            profile, len(out), PROFILE_FLOOR)
    return out
