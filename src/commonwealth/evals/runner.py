"""Run a suite and score it (design/bench.md § 4).

The result carries what a published number needs to be reproducible:
the model, the toolset and how many tools that actually exposed, the
fixture vintage, the public/hidden split, and — printed, never inferred
— how many of the suite's tasks ran. A suite that silently scored three
of forty must be impossible to misread.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .loader import Task, load_suite
from .scoring import Attempt, Score, score_task


class ModelClient(Protocol):
    """What a Tier-2 run needs from a model.

    Given a question and the tools on offer, return the call it would
    make. Deliberately narrow: Tier 2 is single-turn tool selection, and
    a broader interface would invite the runner to grow a chat loop it
    does not need.
    """

    name: str

    async def choose(self, question: str,
                     tools: list[dict]) -> tuple[str | None, dict]: ...


@dataclass
class TaskResult:
    task_id: str
    tier: int
    split: str
    traps: list[str]
    passed: bool
    scores: list[Score]
    attempt: Attempt
    skipped: str | None = None

    def as_dict(self) -> dict:
        return {"task": self.task_id, "tier": self.tier, "split": self.split,
                "traps": self.traps, "passed": self.passed,
                "skipped": self.skipped,
                "called": self.attempt.tool,
                "arguments": self.attempt.arguments,
                "error": self.attempt.error,
                "scores": [s.as_dict() for s in self.scores]}


@dataclass
class RunResult:
    suite: str
    mode: str
    model: str
    toolset: str
    tool_count: int
    started_at: str
    results: list[TaskResult] = field(default_factory=list)
    fixture_recorded_at: str | None = None

    @property
    def executed(self) -> int:
        return sum(1 for r in self.results if r.skipped is None)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed and r.skipped is None)

    def as_dict(self) -> dict:
        by_kind: dict[str, dict[str, int]] = {}
        for r in self.results:
            if r.skipped is not None:
                continue
            for s in r.scores:
                bucket = by_kind.setdefault(s.kind, {"passed": 0, "total": 0})
                bucket["total"] += 1
                bucket["passed"] += 1 if s.passed else 0
        by_trap: dict[str, dict[str, int]] = {}
        for r in self.results:
            if r.skipped is not None:
                continue
            for trap in r.traps or ["(none)"]:
                bucket = by_trap.setdefault(trap, {"passed": 0, "total": 0})
                bucket["total"] += 1
                bucket["passed"] += 1 if r.passed else 0
        return {
            "suite": self.suite, "mode": self.mode, "model": self.model,
            "toolset": self.toolset, "tool_count": self.tool_count,
            "started_at": self.started_at,
            "fixture_recorded_at": self.fixture_recorded_at,
            # The denominator, spelled out three ways so no reading of it
            # can quietly drop the tasks that did not run (§ 4).
            "tasks_in_suite": len(self.results),
            "tasks_executed": self.executed,
            "tasks_skipped": len(self.results) - self.executed,
            "passed": self.passed,
            "by_score_kind": by_kind,
            "by_trap": by_trap,
            "splits": sorted({r.split for r in self.results}),
            "results": [r.as_dict() for r in self.results],
        }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _call_tool(ctx, spec, arguments: dict) -> Attempt:
    """Invoke one tool through the domain function and capture its answer.

    Errors are caught and recorded rather than raised: a typed error is
    a legitimate outcome for several tasks (an unbounded window, an
    unknown capability), and a runner that stopped on one could not
    score them.
    """
    from ..core.errors import CommonwealthError

    try:
        envelope = await spec.fn(ctx, **arguments)
    except CommonwealthError as err:
        return Attempt(tool=spec.name, arguments=arguments, envelope=None,
                       error=f"{err.code}: {err}", calls=[spec.name])
    except TypeError as err:
        return Attempt(tool=spec.name, arguments=arguments, envelope=None,
                       error=f"bad arguments: {err}", calls=[spec.name])
    except AssertionError as err:
        # The replay fetcher refuses an unrecorded request loudly, which
        # is right — but here it means the TASK names a parcel, date or
        # place the fixtures do not contain. That is a broken task, and
        # a broken task has to be scored and reported, not allowed to
        # end the run and take the other tasks' results with it.
        first = str(err).splitlines()[0] if str(err) else "unrecorded request"
        return Attempt(tool=spec.name, arguments=arguments, envelope=None,
                       error=f"no fixture for this call: {first}",
                       calls=[spec.name])
    return Attempt(tool=spec.name, arguments=arguments,
                   envelope=json.loads(envelope.model_dump_json()),
                   calls=[spec.name])


async def run_suite(root: Path, suite: str, ctx, *, profile: str = "default",
                    model: ModelClient | None = None,
                    tier: int | None = None) -> RunResult:
    """Score `suite` against a fixture-backed `ctx`.

    With no `model` this is an oracle run: each task's own expected call
    is executed and the envelope assertions are scored. That measures
    the tasks, not a model — it is what proves a trap can be caught at
    all before anyone pays to find out whether a model catches it.
    """
    from ..core.toolreg import expand_profile
    from ..servers.build import registries

    # The RUN's profile decides what is exposed, not each task's own
    # `toolset` field, because the sweep in #28 asks the same questions
    # at 10, 14 and 16 tools. A task whose expected tool
    # is not in the profile is skipped with that said, rather than
    # scored as a failure the model never had a chance at.
    specs = {s.name: s for s in expand_profile(profile, registries())}
    tasks = load_suite(root, suite)
    # "oracle" rather than a prose stand-in: this string is part of the
    # baseline's identity (§ 4 keys them by suite, model and toolset) and
    # ends up in a filename.
    run = RunResult(suite=suite, mode="model" if model else "oracle",
                    model=model.name if model else "oracle",
                    toolset=profile, tool_count=len(specs),
                    started_at=_now())

    for task in tasks:
        if tier is not None and task.tier != tier:
            run.results.append(TaskResult(
                task.id, task.tier, task.split, task.traps, False, [],
                Attempt(None, {}, None), skipped=f"tier {task.tier}"))
            continue

        if model is None:
            want = task.expected_tool
            if not want:
                # A Tier-3 skill task names a walk rather than one call,
                # so there is nothing for an oracle run to execute. Said
                # plainly instead of scored as a failure.
                run.results.append(TaskResult(
                    task.id, task.tier, task.split, task.traps, False, [],
                    Attempt(None, {}, None),
                    skipped="no single expected call to run in oracle mode"))
                continue
            if want not in specs:
                run.results.append(TaskResult(
                    task.id, task.tier, task.split, task.traps, False, [],
                    Attempt(None, {}, None),
                    skipped=f"{want} is not in the {profile!r} toolset"))
                continue
            attempt = await _call_tool(ctx, specs[want],
                                       task.expected_arguments)
        else:
            tools = [{"name": s.name, "description": s.description}
                     for s in specs.values()]
            chosen, arguments = await model.choose(task.question, tools)
            if chosen is None or chosen not in specs:
                attempt = Attempt(tool=chosen, arguments=arguments,
                                  envelope=None,
                                  error=f"model chose {chosen!r}, which this "
                                        f"toolset does not expose",
                                  calls=[chosen] if chosen else [])
            else:
                attempt = await _call_tool(ctx, specs[chosen], arguments)

        scores = score_task(task, attempt)
        run.results.append(TaskResult(
            task.id, task.tier, task.split, task.traps,
            all(s.passed for s in scores), scores, attempt))
    return run


def write_result(run: RunResult, out_dir: Path) -> Path:
    """One JSON per run, named by what makes it comparable.

    Baselines live in `evals/baselines/` keyed by (suite, model, toolset)
    per § 4, so the filename carries all three — a run that overwrote a
    different model's numbers would silently rewrite history.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-._" else "-"
                   for c in f"{run.suite}-{run.model}-{run.toolset}")
    path = out_dir / f"{safe}.json"
    path.write_text(json.dumps(run.as_dict(), indent=1) + "\n")
    return path


def compare_to_baseline(run: RunResult, baseline: dict,
                        threshold: int = 0) -> list[str]:
    """Regressions against a stored baseline (§ 4).

    Returns the complaints. CI fails on a regression beyond `threshold`
    and only warns on an improvement, because a baseline that updated
    itself on a good day would ratchet quietly and stop being a baseline.
    """
    problems = []
    was = {r["task"]: r["passed"] for r in baseline.get("results", [])}
    now = {r.task_id: r.passed for r in run.results if r.skipped is None}
    for task_id, passed in sorted(now.items()):
        if was.get(task_id) and not passed:
            problems.append(f"{task_id}: passed in the baseline, fails now")
    dropped = sorted(set(was) - set(now))
    if dropped:
        problems.append(
            f"{len(dropped)} task(s) in the baseline did not run: {dropped}")
    lost = baseline.get("passed", 0) - run.passed
    if lost > threshold:
        problems.append(
            f"{lost} fewer tasks pass than the baseline "
            f"({run.passed} vs {baseline.get('passed')}), over the "
            f"threshold of {threshold}")
    return problems
