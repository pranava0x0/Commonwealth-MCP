"""The bench runner (design/bench.md; GitHub issue #28).

Three tiers are specified. Tier 1 lives with the code as ordinary tests
and is reported here rather than owned here. This package owns tiers 2
and 3: load task YAML, run each task against a fixture-backed server,
score mechanically, and write a result with its denominator printed.

Two run modes, and they answer different questions:

  * **oracle** — execute each task's own `expected` call and score the
    envelope assertions. No model, no cost, runnable in CI. It does not
    measure a model; it measures whether the task's ground truth is
    actually achievable, which is what stops a trap passing vacuously
    against a server that cannot produce the answer the trap asserts.
  * **model** — the real Tier-2 measurement: give a model the question
    and the toolset, and score what it picked. This costs money and is
    the one thing in #28 that cannot be run for free.

Running the model sweep is not the same as being ready to. Oracle mode
exists so everything except the model call is proven first.
"""
from .loader import Task, TaskLoadError, load_suite, suites  # noqa: F401
from .runner import RunResult, TaskResult, run_suite  # noqa: F401
