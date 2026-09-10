"""Task files: the design/bench.md § 2 format, loaded and checked.

A task that names a tool the toolset does not expose, a fixture that is
not on disk, or a trap kind the spec does not define is a broken task,
and a broken task that loads quietly is worse than one that fails —
it scores as a failure and reads as a finding about the model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# design/bench.md § 2. Every kind here is a distinct way an answer can be
# wrong in a way that looks right, which is why the spec asks for one
# task per kind per domain.
TRAP_KINDS = {"ambiguity", "registry_gap", "outage", "stale", "overreach",
              "injection"}

# The scorers implemented in `scoring.py`. Listed here so a task naming
# one that does not exist fails at load rather than scoring zero.
SCORE_KINDS = {"tool_choice", "argument_match", "provenance_present",
               "coverage_honesty", "restraint", "no_injection_followed",
               # The Tier-3 rollups from design/bench.md § 1, used by the
               # skill suites that shipped with #27.
               "source_and_jurisdiction", "retrieval_correctness"}


class TaskLoadError(Exception):
    """A task file that cannot be trusted to score anything."""


@dataclass
class Task:
    id: str
    tier: int
    question: str
    toolset: str
    path: Path
    fixtures: list[str] = field(default_factory=list)
    expected: dict[str, Any] = field(default_factory=dict)
    score: list[str] = field(default_factory=list)
    traps: list[str] = field(default_factory=list)
    skill: str | None = None
    # Which half of the public/hidden split this came from (§ 3). Carried
    # into the result so a published number always says what it was
    # measured over.
    split: str = "public"
    note: str = ""

    @property
    def expected_tool(self) -> str | None:
        return self.expected.get("tool")

    @property
    def expected_arguments(self) -> dict[str, Any]:
        return dict(self.expected.get("arguments") or {})


def _require(doc: dict, key: str, path: Path) -> Any:
    if key not in doc:
        raise TaskLoadError(f"{path}: task has no {key!r}")
    return doc[key]


def load_task(path: Path, split: str = "public") -> Task:
    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as err:
        raise TaskLoadError(f"{path}: not valid YAML ({err})") from err
    if not isinstance(doc, dict):
        raise TaskLoadError(f"{path}: task file is not a mapping")

    traps = list(doc.get("traps") or [])
    unknown = set(traps) - TRAP_KINDS
    if unknown:
        raise TaskLoadError(
            f"{path}: unknown trap kind(s) {sorted(unknown)}; "
            f"design/bench.md § 2 defines {sorted(TRAP_KINDS)}")

    raw_score = doc.get("score") or []
    kinds = [s["kind"] if isinstance(s, dict) else str(s) for s in raw_score]
    unknown = set(kinds) - SCORE_KINDS
    if unknown:
        raise TaskLoadError(
            f"{path}: no scorer for {sorted(unknown)}; implemented "
            f"scorers are {sorted(SCORE_KINDS)}")
    if not kinds:
        raise TaskLoadError(
            f"{path}: task scores nothing, so it can never fail")

    return Task(
        id=str(_require(doc, "id", path)),
        tier=int(_require(doc, "tier", path)),
        question=str(_require(doc, "question", path)),
        toolset=str(doc.get("toolset") or "default"),
        path=path,
        fixtures=list(doc.get("fixtures") or []),
        expected=dict(doc.get("expected") or {}),
        score=kinds,
        traps=traps,
        skill=doc.get("skill"),
        split=split,
        note=str(doc.get("note") or ""),
    )


def _suite_dirs(root: Path) -> dict[str, Path]:
    """Every directory of tasks under `root`, keyed by its suite name.

    `tasks/<suite>` is the public set; `skills/<skill>` are the Tier-3
    walks that already shipped with #27. Both are suites — the runner
    does not care which directory a task came from, only what tier it
    declares.
    """
    out: dict[str, Path] = {}
    for parent, prefix in ((root / "tasks", ""), (root / "skills", "skill:")):
        if not parent.is_dir():
            continue
        for child in sorted(parent.iterdir()):
            if child.is_dir() and any(child.glob("*.yaml")):
                out[prefix + child.name] = child
    return out


def suites(root: Path) -> dict[str, Path]:
    return _suite_dirs(root)


def load_suite(root: Path, suite: str) -> list[Task]:
    """Every task in `suite`, public set then hidden set.

    The hidden half (§ 3) is maintainer-held and normally absent from a
    checkout. When it is present it loads from the same layout under
    `hidden/`, so a release run scores both without a second code path —
    the split ships from day one even while the hidden set is empty,
    because retrofitting it later re-litigates every published number.
    """
    found = _suite_dirs(root)
    if suite not in found:
        raise TaskLoadError(
            f"unknown suite {suite!r}; found {sorted(found) or 'none'}")
    tasks = [load_task(p, "public") for p in sorted(found[suite].glob("*.yaml"))]

    hidden_root = root / "hidden"
    hidden = _suite_dirs(hidden_root).get(suite) if hidden_root.is_dir() else None
    if hidden:
        tasks += [load_task(p, "hidden") for p in sorted(hidden.glob("*.yaml"))]

    ids = [t.id for t in tasks]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise TaskLoadError(
            f"suite {suite!r} has more than one task with id(s) {dupes}; "
            "a result keyed by task id would silently keep one of them")
    return tasks
