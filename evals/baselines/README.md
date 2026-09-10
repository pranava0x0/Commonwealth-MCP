# Baselines

One JSON per (suite, model, toolset), which is how `design/bench.md` § 4
says to key them. The filename carries all three, so a run cannot
silently overwrite a different model's numbers.

The files here are **oracle** runs: each task's own expected call
executed against the recorded fixtures, no model involved. They are a
floor, not a score — they say the tasks are answerable and the traps are
catchable, which is the thing worth knowing before paying for a model
run.

Model-run baselines arrive with their model, token spend and date beside
them (§ 6). A bench score without its cost and vintage is not
reproducible, so a file here without those is an oracle run by
definition.

Regenerate deliberately:

```bash
commonwealth eval run tier2 --profile default --out evals/baselines
```

Never automatically. An improvement warns; a regression fails. A
baseline that moved on its own would stop being one.
