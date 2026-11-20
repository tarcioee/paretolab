# Web interface

```bash
paretolab ui experiment.yaml                          # opens http://127.0.0.1:8765/ in the browser
paretolab ui new.yaml --project project.yaml          # a new setup, created on the first save
paretolab ui experiment.yaml --port 9000 --no-browser
paretolab ui experiment.yaml --lang pt-BR             # default language when the browser has not chosen one
```

The interface is one more front end of the command line. It does not run anything itself:

- it writes `experiment.yaml`;
- it starts `paretolab run` and `paretolab analyze` as separate processes;
- it reads `state.json`, the run results and `analysis/summary.json`.

Closing the interface (Ctrl+C in its terminal) does not stop an experiment. An experiment started from a terminal shows up in the interface too, and can be paused from it.

## Three steps

The header shows the project (title, subtitle, icon) and three steps. The interface opens on the step that matches the experiment: setup when nothing ran yet, run while it runs, analysis when it is finished.

| Step | What it does |
|---|---|
| **1 · Setup** | A form built from the project manifest. Shortcuts fill it in ("complete", "quick test": one instance, one seed, a tenth of the budget, no tuning; "saved setup"). Then: output folder; what to run (tuning on or off, a matrix of algorithms × variants when they share their variants, instances); size (evaluations, seeds, time limit in s, min or h); computer resources (parallel runs, kill grace, free disk); parameters; tuning; and, folded, the analysis settings and the YAML that will be saved. A bar at the bottom shows how many runs the setup makes and every problem found by the server, which validates with the same code as `paretolab validate`. "Run" asks for confirmation, saves and starts. |
| **2 · Run** | *Progress*: pause, resume or run again; a picture of a Pareto front forming as the runs finish; a progress bar; finished runs, failures, processes in use, elapsed time and the estimated time left; the tuning of each variant. *Instances*: every instance with its own progress, and a table of finished / planned runs per variant and instance. *Details*: the setup in use, the folders, the logs and the project (objectives, instances, algorithms, command). |
| **3 · Analysis** | *Charts*: choose the chart (critical difference, box plot, ECDF, attainment, convergence), the indicator and the instance; under it, the matching statistical test (Friedman, Nemenyi, mean ranks, Wilcoxon-Holm). *Tables*: mean (standard deviation) per instance of each indicator, with CSV, Markdown and LaTeX files. *Experiment information*: parameters used (the tuned ones marked), times per variant, metadata and files, warnings. "Analyse now" analyses the runs finished so far. |

### Parameters in the form

Each algorithm has a table with one row per parameter. The columns are the general value (the key `algorithm` in the setup) and one column per variant (`algorithm/variant`, which wins).

- An empty cell uses the manifest default.
- With tuning enabled, an empty cell is **tuned**, and a value fixes the parameter, so it is not tuned.

## Languages

The language selector in the header switches between English (the default) and Portuguese; the choice is kept in the browser. The texts are in `src/paretolab/web/static/i18n/<language>.json`: to add a language, copy `en.json`, translate the values and add the language to `LANGUAGES` in `server.py`. A test checks that every language has the same keys and placeholders.

Messages written by paretolab itself (validation problems, warnings of the analysis, the state of the experiment) carry a code and arguments next to their English text, so the interface translates them as well. Figures and tables are written in English.

## The project's own look

A manifest can give the interface a title, a subtitle, a colour, an icon and its own words for the concepts (for instance "strategy" instead of "variant"), and descriptions of objectives, instances, algorithms, variants and parameters, shown as help. See the `ui` block in [CONTRACT.md](CONTRACT.md). Everything is optional.

## Saving

- The setup is saved only when it is valid, and not while the experiment is running.
- The previous file is kept as `experiment.yaml.bak`.
- The saved file contains only the values that differ from the defaults, in the order of the documentation. **Comments in the file are lost;** edit the file by hand if you want to keep them.

## Files

The screen output of the processes started by the interface goes to `<output_dir>/ui_run.log` and `<output_dir>/ui_analyze.log`. The run details show them next to `paretolab.log`.

## Safety

- The interface listens on 127.0.0.1 only. It has no authentication: it is meant for one user on one machine.
- Requests whose `Host` or `Origin` is not that address are refused. This blocks other web sites and DNS rebinding.
- Changes need a JSON body, so a plain form on another site cannot post to it.
- Only files inside the output folder are served, plus the project's `ui.icon` when it is inside the project's folder.
- On Windows, the port is taken exclusively; if it is in use, the next free port is used.

Two `paretolab run` on the same output folder are refused: the second one sees the first one's process in `state.json`.

## Dependencies

None beyond paretolab's own: the server is Python's `http.server`, and the page is plain HTML, CSS and JavaScript modules, with no build step and nothing loaded from the internet. It needs a browser from 2023 or later (it uses CSS `color-mix`).
