# Tuning

With `tuning.enabled: true`, `paretolab run` tunes every algorithm variant of the experiment before its runs. The runs then use the tuned values.

```yaml
tuning:
  enabled: true
  tuner: irace               # the only backend so far
  max_experiments: 2000      # runs the tuner may spend, per algorithm variant
  instances: [gr17]          # training instances; default: the experiment's instances
  budget: {max_evaluations: 20000}   # budget of each tuning run; default: the experiment's budget
  seed: 1                    # the tuner's own seed
  bounds:                    # multi-objective only, optional: [min, max] per objective, per instance
    A: [[0, 900], [100, 400]]
  calibration_runs: 3        # multi-objective only: runs per variant used to find the missing bounds
```

`paretolab doctor` checks that R and the irace package are installed. On Windows, Rscript does not have to be on the PATH: the usual install folders are searched. `PARETOLAB_RSCRIPT` can point to a specific one.

## What is tuned

- One tuning per algorithm variant (a *unit*), on the training instances.
- The search space is the parameter list of the algorithm in the manifest, with types, ranges, `log` and `condition`.
- **Parameters fixed in the setup's `parameters` are not tuned.** A unit with nothing left to tune is skipped.
- The planned configuration (manifest defaults plus setup values) is given to irace as its first candidate, when it sets every tuned parameter and none of them has a condition.

## The cost of a run

The tuner minimizes a cost computed by paretolab's generic target runner, which runs your program exactly as an experiment run would.

- **Single-objective:** the best value of the front, negated when the objective is maximized. A run without any solution costs `1e300`.
- **Multi-objective:** minus the hypervolume of the front.
  - The front is normalized with **fixed bounds per training instance**, so that every run on an instance is measured the same way.
  - The reference point sits at `1 + normalization.reference_offset` in every objective.
  - An empty front costs 0.
  - Bounds come from `tuning.bounds`. Missing bounds are **calibrated**: each variant runs its planned configuration `calibration_runs` times on the instance, and the bounds are the minimum and maximum of all those fronts. They are stored in `tuning/bounds.json` and reused.
  - A better configuration can go past the calibrated bounds; that only raises its hypervolume. A configuration much worse than the defaults can end up beyond the reference point, with hypervolume 0.

irace compares configurations by ranks on each instance (Friedman test, by default), so only the order of the costs within an instance matters.

A run that fails (non-zero exit code, invalid output, `status: error`, killed after its time limit) stops irace with that error. Fix the program and run again.

## Resume and pause

- `<output_dir>/tuning/<algorithm>/<variant>/best.json` marks a unit as done. It is never tuned again; delete the file to redo it.
- `paretolab pause` or Ctrl+C stops irace and everything it started.
- The next `paretolab run` passes irace's last saved log as `recoveryFile`. irace replays what it had already evaluated and goes on from there.
  - irace 4 saves its log at most once a minute, so up to a minute of work may be redone.
  - If irace cannot resume (for example, when it was paused before its first save), the unit starts over.

## Files

In `<output_dir>/tuning/`:

| File | Contents |
|---|---|
| `bounds.json` | calibrated bounds per training instance (multi-objective) |
| `calibration/` | fronts of the calibration runs |
| `<algorithm>/<variant>/best.json` | the tuned values, the fixed ones, the tuner version, budget and duration |
| `<algorithm>/<variant>/scenario.txt`, `parameters.txt`, `instances.txt`, `configurations.txt` | irace inputs, written from the setup (do not edit them; edit the setup) |
| `<algorithm>/<variant>/target.json`, `target_runner.bat` or `.sh` | the target runner's configuration and wrapper |
| `<algorithm>/<variant>/irace.Rdata`, `irace_output.txt` | irace's log and its screen output (every attempt is appended) |

The best configuration is read from irace's output (`# Best configurations as commandlines`) and, if that fails, from `irace.Rdata` through R.

## Writing another backend

A backend subclasses `paretolab.tuning.Tuner`, implements `check()` and `tune(unit, should_stop, log)`, and is registered in `paretolab.tuning.manager.TUNERS`. paretolab gives it a `TuningUnit` with the parameter space, the training instances, the budget in experiments and the target runner's configuration. The backend calls `python -m paretolab.tuning.target`, or `paretolab.tuning.target.evaluate`, to get the cost of a configuration.

## License

irace is GPL-2+. paretolab does not ship or link it: it writes irace's input files and runs R as a separate program.
