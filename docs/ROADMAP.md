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

## Result schema (draft)

Each run writes one `result.json` file with these fields:

- `schema_version`.
- Run identity: instance, algorithm, variant, seed and parameters.
- `objectives_sense`.
- `status`: `ok`, `timeout` or `error`.
- Effort: evaluations and wall time.
- Solutions: `front` (objective vectors), with optional `variables` and `constraints`.
- `convergence_trace` (optional).
- `metadata`, which is free-form. The core ignores it and only plugins read it.

## Phases

1. **Repository skeleton.** Packaging, CLI, CI on Windows and Linux. *(done)*
2. **Contracts.**
   - Schemas for the manifest, the setup and the results.
3. **Analysis.**
   - Multi-objective indicators for any number of objectives (moocore).
   - EAF plots.
   - Single-objective analysis: gap, convergence curves and ECDF.
   - Statistics, tables and plots.
4. **Execution.**
   - Port the state, pause and resume, parallel runs and per-run time limit.
   - Name-based registries.
5. **Tuning.** The `Tuner` interface and the irace backend, with `recoveryFile` to resume an interrupted tuning unit.
6. **Web interface.** Driven by the manifest.
7. **Validation.**
   - ZDT1 in Python and DTLZ2 in C++.
   - A small TSP from TSPLIB with a known optimum, for example burma14 and gr17.
8. **Release v0.1.**

## Later versions

- **v0.2:** optional `checkpoint_in` / `checkpoint_out` in the contract, so a single run can resume in the middle. Also a small C++ header and a Python helper for writing `result.json`.
- **v0.3:** a Python adapter that calls the algorithm in-process, without one subprocess per run.
- **Later:** more tuners (SMAC3, Optuna), an SQLite state backend if run counts demand it, and PyPI with a Zenodo DOI from v1.0.

## Out of scope

- Problem-as-black-box IPC, where an external process evaluates one solution at a time.
- Shipping PISA. It is not used. Indicators come from moocore.
