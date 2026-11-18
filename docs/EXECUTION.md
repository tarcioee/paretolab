# Running an experiment

```bash
paretolab run experiment.yaml            # run (or resume) every planned run, then analyse
paretolab run experiment.yaml -j 8       # 8 runs at a time (default: setup.parallel_jobs, 0 = all cores)
paretolab run experiment.yaml --retry-failed
paretolab pause experiment.yaml          # from another terminal; or press Ctrl+C
paretolab status experiment.yaml
```

## One run

1. paretolab creates `runs/<instance>/<algorithm>/<variant>/seed_<n>/` and builds the command from the manifest.
   - The program's working directory is the folder of `project.yaml`.
   - `{result_file}` is `output.json` inside the run folder.
   - `{output_dir}` is the run folder itself.
2. The program's standard output and error go to `log.txt` in the run folder.
3. When the program ends with exit code 0, `output.json` is validated against the project. paretolab then stores `result.json`, which has:
   - the program's output;
   - the run's identity and parameters;
   - in `metadata.paretolab`: the exact command, the measured time and the paretolab version.

   `output.json` and `log.txt` are then removed.
4. Anything else is stored as a `result.json` with `status: error` and the reason, and `log.txt` is kept. That covers:
   - a non-zero exit code;
   - a missing or invalid output;
   - a program that cannot be started;
   - a run that exceeds its time limit.

### Parameters

Each run's parameters are built in layers. A later layer wins over an earlier one:

1. the defaults in the manifest;
2. `setup.parameters["<algorithm>"]`;
3. `setup.parameters["<algorithm>/<variant>"]`;
4. tuned values (phase 5).

### Time limit

The program receives `{time_limit_s}` and should stop by itself, writing its best front.

A run still alive at `time_limit_s + kill_grace_s` is killed, together with every process it started:

- on Windows with `taskkill /T`;
- elsewhere through its process group.

The default `kill_grace_s` is the larger of 10 s and 10% of the limit.

## Resume, pause, failures

- **Resume** works per run. A run that already has a `result.json` is never repeated, so `paretolab run` can be called again at any time.
- **Pause** works two ways:
  - `paretolab pause` creates `<output_dir>/PAUSE`;
  - pressing Ctrl+C has the same effect.

  The runs in progress are stopped, and their folders are deleted. The next `paretolab run` starts them over.
- **Failures** are stored and counted. `--retry-failed` runs them again.
- **Disk:** before each launch, the free space on the output disk is checked. Below `min_free_disk_gb` (default 1 GB), the experiment pauses with exit code 3.
- **Configuration changes:** `experiment_used.json` stores the setup and project of the last run. If either changed since then, paretolab says so, because the stored results came from the previous version.
- **Safety net on Windows:** if paretolab itself is killed abruptly, a Job Object makes Windows kill the runs too.

## Files in `<output_dir>`

| File | Contents |
|---|---|
| `runs/.../result.json` | one per finished run, the source of truth |
| `state.json` | phase, counts, runs in progress, mean run time, estimated time left (read by `status` and the web interface) |
| `paretolab.log` | timestamped messages, including failures |
| `experiment_used.json` | setup and project of the last run |
| `analysis/` | written by `paretolab analyze`, which `run` also calls at the end |

Exit codes: 0 = done or paused, 1 = unexpected error, 2 = invalid setup or project, 3 = paused for lack of disk space.
