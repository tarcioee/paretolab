# Contract (schema version 1)

paretolab talks to your code through three files. Check any of them with:

```bash
paretolab validate <file>                       # the kind of file is detected from its keys
paretolab validate result.json --project project.yaml
paretolab schema project|setup|output|result    # JSON Schema, for editors and other languages
```

Names of objectives, instances, algorithms, variants and parameters may use only letters, digits, `_`, `.` and `-`. The first character must be a letter or a digit. These names end up in folder names and on command lines.

Unknown keys are rejected, so a typo is reported as an error instead of being silently ignored.

## 1. Project manifest (`project.yaml`): what the problem is

```yaml
name: tsp
objectives:                       # one objective = single-objective project
  - {name: length, sense: min}    # sense: min | max; optional: unit
instances:
  - {name: burma14, path: instances/burma14.tsp, optimum: 3323}   # optimum: single-objective only (enables "gap")
  - gr17                                                          # shorthand for {name: gr17}
algorithms:
  - name: ils
    variants: [first, best]       # optional; default [default]. Each variant is tuned and compared on its own
    parameters:                   # tuning space (irace types)
      - {name: k, type: integer, range: [1, 10], default: 3}
      - {name: t0, type: real, range: [0.01, 100], log: true}
      - {name: move, type: categorical, values: [2opt, oropt], default: 2opt}
      - {name: alpha, type: real, range: [0, 1], condition: "move == 'oropt'"}   # condition is passed to irace as is
executable: ./ils                 # optional; used as {executable}
command: ["{executable}", "{instance_path}", "--seed", "{seed}", "--evals", "{max_evaluations}",
          "--out", "{result_file}", "{params}"]
param_format: "--{name}={value}"  # how each parameter becomes arguments; e.g. "--param {name}={value}"
```

`command` describes one run. It can be written as a list of tokens, which is recommended, or as one string that is split the way a POSIX shell would split it. No shell is ever involved: each value is passed as a single argument, even when it contains spaces.

### Placeholders

| Placeholder | Value |
|---|---|
| `{executable}` | the `executable` field |
| `{instance}`, `{instance_path}` | the instance name, and its `path` (the name if there is no path) |
| `{algorithm}`, `{variant}` | the algorithm and variant being run |
| `{seed}` | the run's seed. **Required.** |
| `{max_evaluations}`, `{time_limit_s}` | the budget from the setup |
| `{output_dir}`, `{result_file}` | where to write. **At least one is required.** |
| `{params}` | expands to the parameter arguments. It must be a token of its own. |

## 2. Experiment setup (`experiment.yaml`): what to run

```yaml
project: project.yaml           # relative to this file
output_dir: results/exp1
instances: [burma14, gr17]      # default: all instances
algorithms: [ils/first, sa]     # "alg" = all its variants, "alg/variant" = one; default: all
seeds: {count: 30, start: 1}    # or an explicit list: [1, 2, 3]
budget: {max_evaluations: 100000, time_limit_s: 60}   # at least one; the time limit is per run
parallel_jobs: 0                # 0 = number of CPU cores
tuning: {enabled: true, tuner: irace, max_experiments: 2000, instances: [gr17]}
indicators: [best, gap]         # default: hv + igd_plus (multi); best (+ gap when all optima are known) (single)
normalization: {method: minmax, reference_offset: 0.1}   # HV reference point at 1.1 per objective
statistics: {tests: [friedman, nemenyi, wilcoxon_holm], alpha: 0.05}
```

The available indicators depend on the project:

- **Multi-objective:** `hv`, `igd_plus`, `igd`, `epsilon_additive`.
- **Single-objective:** `best`, `gap`.

`paretolab validate experiment.yaml` checks the setup against its project. It lists every unknown name at once and prints the number of runs.

## 3. Run output (what your program writes to `{result_file}`)

Only `front` is required:

```json
{
  "front": [[3323.0]],
  "status": "ok",
  "evaluations": 100000,
  "wall_time_s": 12.4,
  "variables": [[0, 13, 2, 5]],
  "convergence_trace": [{"evaluations": 1000, "time_s": 0.1, "front": [[3600.0]]}],
  "metadata": {"anything": "you like"}
}
```

- **`front`:** the final solutions as objective vectors, in the order of the project's objectives.
  - Write only feasible solutions. Write `[]` when none was found.
  - A single-objective run writes its best value as `[[value]]`.
  - Values must be finite: no NaN or infinity.
- **`status`:** one of
  - `ok`;
  - `timeout`: the time limit stopped the run, and the front is still valid;
  - `error`: the front is ignored. Explain why in `error_message`.
- **`variables`:** optional, one entry per point of `front`.
- **`metadata`:** free-form. paretolab ignores it, and plugins may read it.

paretolab adds the run's identity itself (instance, algorithm, variant, seed, parameters and objectives) and stores the complete record as a *run result*, shown by `paretolab schema result`. Your program never needs to echo these fields back.
