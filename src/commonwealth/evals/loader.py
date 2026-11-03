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
    # A full walk needs a sequence of calls and a composed answer. Its
    # rubric is not a list of assertions about one tool's envelope.
    walk: dict[str, Any] | None = None

    @property
    def expected_tool(self) -> str | None:
        return self.expected.get("tool")

    @property
    def expected_arguments(self) -> dict[str, Any]:
        return dict(self.expected.get("arguments") or {})


_Text = Annotated[str, Field(pattern=r"\S")]


@with_config(ConfigDict(extra="forbid"))
class _Expected(TypedDict, total=False):
    tool: _Text
    arguments: dict[str, JsonValue]
    coverage: dict[str, str]
    requires_user_choice: bool
    found: bool
    answerable: bool
    next_action: str
    jurisdiction: str
    must_warn: list[str]
    must_say: list[_Text]
    must_not_say: list[_Text]
    candidates: list[str]
    sources_returned: list[str]
    max_calls: Annotated[int, Field(ge=0)]
    record_count_over: Annotated[int, Field(ge=0)]
    data: dict[str, JsonValue]


@with_config(ConfigDict(extra="allow"))
class _Walk(_Expected, total=False):
    """Additional facts about individual steps, partners and the final answer."""


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
    walk: NotRequired[_Walk]
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


# The single-call fields each scorer consumes. Empty sets denote checks
# on the response itself, such as the presence of evidence on a hit.
_INPUTS = {
    "provenance_present": set(),
    "no_injection_followed": set(),
    "tool_choice": {"tool"},
    "argument_match": {"arguments"},
    "coverage_honesty": {"coverage", "must_warn", "next_action", "requires_user_choice"},
    "source_and_jurisdiction": {"jurisdiction", "sources_returned", "candidates"},
    "retrieval_correctness": {"must_say", "must_not_say", "found", "answerable",
                              "record_count_over", "data"},
    "restraint": {"max_calls"},
}


SCORE_KINDS = set(_INPUTS)


def _check_inputs(path: Path, kinds: list[str], expected: dict, traps: list[str]) -> None:
    consumed = {"tool", "arguments"}  # Also used to execute an oracle call.
    for kind in kinds:
        inputs = _INPUTS[kind]
        consumed.update(inputs)
        if not inputs or (kind == "restraint" and "overreach" in traps):
            continue  # These checks read the envelope or call trace directly.
        # False and zero are meaningful boolean and numeric expectations.
        if not any(isinstance(expected.get(key), int) or expected.get(key) for key in inputs):
            raise TaskLoadError(f"{path}: score.{kind} needs an assertion in expected: "
                                f"{', '.join(sorted(inputs))}")
    unused = expected.keys() - consumed
    if unused:
        raise TaskLoadError(f"{path}: no declared scorer reads expected field(s) {sorted(unused)}")


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
    walk = doc.get("walk")
    if walk is not None:
        if not walk or doc["tier"] != 3 or not doc.get("skill"):
            raise TaskLoadError(f"{path}: walk needs a nonempty rubric, tier 3 and a skill")
        if "score" in doc or "expected" in doc:
            raise TaskLoadError(f"{path}: walk cannot also declare single-call expected or score")
    elif not kinds:
        raise TaskLoadError(
            f"{path}: task scores nothing, so it can never fail")
    else:
        _check_inputs(path, kinds, doc.get("expected", {}), traps)

    return Task(
        id=doc["id"],
        tier=doc["tier"],
        question=doc["question"],
        toolset=str(doc.get("toolset") or "default"),
        path=path,
        fixtures=fixtures,
        expected=dict(doc.get("expected") or {}),
        score=kinds,
        walk=walk,
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
