"""Task files: the design/bench.md § 2 format, loaded and checked.

A task that names a tool the toolset does not expose, a fixture that is
not on disk, or a trap kind the spec does not define is a broken task,
and a broken task that loads quietly is worse than one that fails —
it scores as a failure and reads as a finding about the model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from pydantic import BeforeValidator, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError, with_config
from typing_extensions import NotRequired, TypedDict

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


# Preserve additional walk-specific assertions for the multi-step skill tasks.
# Fields consumed directly by a scorer have an explicit, non-coercing type.
@with_config(ConfigDict(extra="allow"))
class _Expected(TypedDict, total=False):
    tool: str
    arguments: dict[str, JsonValue]
    coverage: dict[str, str]
    requires_user_choice: bool
    found: bool
    answerable: bool
    next_action: str
    jurisdiction: str
    must_warn: list[str]
    must_say: list[str]
    must_not_say: list[str]
    candidates: list[str]
    sources_returned: list[str]
    max_calls: Annotated[int, Field(ge=0)]
    record_count_over: int


@with_config(ConfigDict(extra="forbid"))
class _Score(TypedDict):
    kind: str


def _score_rule(value: object) -> object:
    """Keep the compact score: [tool_choice] spelling."""
    return {"kind": value} if isinstance(value, str) else value


@with_config(ConfigDict(extra="forbid"))
class _TaskFile(TypedDict):
    id: str
    tier: Annotated[int, Field(ge=2, le=3)]
    question: str
    toolset: NotRequired[str]
    expected: NotRequired[_Expected]
    score: NotRequired[list[Annotated[_Score, BeforeValidator(_score_rule)]]]
    traps: NotRequired[list[str]]
    fixtures: NotRequired[list[str]]
    skill: NotRequired[str]
    partner: NotRequired[str]
    inject: NotRequired[dict[str, JsonValue]]
    note: NotRequired[str]


# YAML also admits dates, sets, non-string keys, and non-finite numbers.
# Check the entire document, including walk-specific fields, before it can
# reach a scorer or be copied into a JSON transcript by write_result.
_TASK_FILE = TypeAdapter(_TaskFile)
_JSON_DOCUMENT = TypeAdapter(dict[str, JsonValue], config=ConfigDict(allow_inf_nan=False))


def load_task(path: Path, split: str = "public") -> Task:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeError) as err:
        raise TaskLoadError(f"{path}: not valid YAML ({err})") from err
    if not isinstance(raw, dict):
        raise TaskLoadError(f"{path}: task file is not a mapping")

    try:
        doc = _TASK_FILE.validate_python(raw, strict=True)
        _JSON_DOCUMENT.validate_python(raw, strict=True)
    except ValidationError as err:
        first = err.errors(include_url=False, include_input=False)[0]
        location = ".".join(str(part) for part in first["loc"])
        hint = " (quote dates as strings)" if first["type"] == "invalid-json-value" else ""
        raise TaskLoadError(f"{path}: {location}: {first['msg']}{hint}") from err

    fixtures = doc.get("fixtures", [])
    # A declared fixture that is not on disk makes the declaration
    # meaningless, and `eval validate` accepting a misspelled or deleted
    # directory is exactly how it stops being a check. The names are
    # checked here so the failure names the file, not a replay miss
    # three layers down.
    from ..fixtures import fixture_names

    known = set(fixture_names())
    missing = sorted(set(fixtures) - known)
    if missing:
        raise TaskLoadError(
            f"{path}: declares fixture(s) {missing} that are not recorded; "
            f"known fixtures are {sorted(known)}")

    traps = list(doc.get("traps") or [])
    unknown = set(traps) - TRAP_KINDS
    if unknown:
        raise TaskLoadError(
            f"{path}: unknown trap kind(s) {sorted(unknown)}; "
            f"design/bench.md § 2 defines {sorted(TRAP_KINDS)}")

    raw_score = doc.get("score") or []
    kinds = [s["kind"] for s in raw_score]
    unknown = set(kinds) - SCORE_KINDS
    if unknown:
        raise TaskLoadError(
            f"{path}: no scorer for {sorted(unknown)}; implemented "
            f"scorers are {sorted(SCORE_KINDS)}")
    if not kinds:
        raise TaskLoadError(
            f"{path}: task scores nothing, so it can never fail")

    return Task(
        id=doc["id"],
        tier=doc["tier"],
        question=doc["question"],
        toolset=str(doc.get("toolset") or "default"),
        path=path,
        fixtures=fixtures,
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
