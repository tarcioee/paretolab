# Roadmap

## Design decisions

| Topic | Decision |
|---|---|
| Plug-in point | A command-line contract. The user provides a command template, for example `"{exe} -i {instance} -s {seed} {params}"`, and the program writes a result JSON file. It works with any language. |
| Configuration | YAML files: a project manifest (what the problem is) and an experiment setup (what to run). Both are validated with Pydantic. |
| Objectives | Single-objective and multi-objective. Each objective has a sense, `min` or `max`. |
| Indicators | moocore. The defaults are HV and IGD+ for multi-objective runs, and the gap to the optimum (or the best value found) for single-objective runs. |
| Statistics | Friedman, Nemenyi and Wilcoxon-Holm, fixed and declared in the setup. They are never chosen automatically. Critical-difference diagrams are included. |
| Tuning | A `Tuner` interface. irace is the first backend: paretolab writes the scenario files and acts as the target runner. |
| State | JSON files behind an interface, with pause and resume, including during tuning. |
| UI | A local web interface whose labels come from the manifest. |
| Distribution | GitHub only until v1.0. |
| License | MPL-2.0. |

## Contract

The contract is specified in [CONTRACT.md](CONTRACT.md).

The user's program writes a minimal *run output*. Only `front` is required. Optional fields are `status`, `evaluations`, `wall_time_s`, `variables`, `convergence_trace` and `metadata`. paretolab then adds the run's identity and stores the complete *run result*.

Infeasible solutions are not part of the front. A per-solution `constraints` field was considered and left out until a use appears.

## Phases

1. **Repository skeleton.** Packaging, CLI, CI on Windows and Linux. *(done)*
2. **Contracts.** *(done)*
   - Schemas for the manifest, the setup and the results.
   - `paretolab validate` and `paretolab schema`.
3. **Analysis.** *(done; see [ANALYSIS.md](ANALYSIS.md))*
   - Multi-objective indicators for any number of objectives (moocore).
   - EAF plots.
   - Single-objective analysis: gap, convergence curves and ECDF.
   - Statistics, tables and plots.
   - `paretolab analyze`.
   - Still open:
     - with 3 or more objectives there is no front plot (parallel coordinates are a candidate);
     - there is no multi-objective convergence plot from `convergence_trace` yet.
4. **Execution.** *(done; see [EXECUTION.md](EXECUTION.md))*
   - Ported the state, pause and resume, parallel runs and per-run time limit.
     - Resume now works per run, not per instance.
     - Failures are stored as results.
     - When a run is killed, everything it started is killed too.
   - Name-based registries: covered by the manifest, since algorithms, variants and parameters are declared there.
   - Not tested automatically: Ctrl+C. Pausing through the PAUSE file is tested.
5. **Tuning.** *(done; see [TUNING.md](TUNING.md))*
   - The `Tuner` interface and the irace backend, run by `paretolab run` before the runs.
   - A generic target runner: the cost is the best value (single-objective) or minus the normalized hypervolume (multi-objective), with fixed bounds per instance that are given or calibrated.
   - Resuming per unit (`best.json`), and inside a unit through irace's `recoveryFile`.
   - `paretolab doctor` finds Rscript outside the PATH and reports the irace version.
   - Checked with irace 4.5.1 on a toy problem: it found the known optimum, and a paused unit resumed without repeating finished iterations. CI uses a stand-in for irace, because it has no R.
6. **Web interface.** *(done; see [WEB.md](WEB.md))*
   - `paretolab ui`: a local page whose setup form is built from the manifest, with live validation, start, pause and resume, progress per instance and variant, tuning status, logs, and the analysis (tables, tests, figures).
   - Standard library only (`http.server`, plain JavaScript); listens on 127.0.0.1 and refuses other hosts and origins.
   - Two runs on the same output folder are now refused, and a pause requested while a run is starting is kept.
   - Second version: three steps (setup, run, analysis), English and Portuguese with a language selector, the project's own title, colour, icon and words (`ui` in the manifest), descriptions as help, charts chosen by kind, indicator and instance with the matching test, and messages coded so they can be translated.
7. **Validation.** *(done; see [examples/](../examples))*
   - Examples, each run end to end by `tests/test_examples.py`:
     - TSP (Python, single-objective): burma14 and gr17 from TSPLIB, whose optima (3323, 2085) are checked by Held-Karp;
     - ZDT1 (Python, 2 objectives);
     - DTLZ2 (C++, 3 objectives).
   - `{python}` placeholder and project-relative `executable` (with `.exe` on Windows), so examples run the same on both systems.
8. **Release v0.1.**

## Later versions

- **v0.2:** optional `checkpoint_in` / `checkpoint_out` in the contract, so a single run can resume in the middle. Also a small C++ header and a Python helper for writing `result.json`.
- **v0.3:** a Python adapter that calls the algorithm in-process, without one subprocess per run.
- **Later:** more tuners (SMAC3, Optuna), an SQLite state backend if run counts demand it, and PyPI with a Zenodo DOI from v1.0.

## Out of scope

- Problem-as-black-box IPC, where an external process evaluates one solution at a time.
- Shipping PISA. It is not used. Indicators come from moocore.
