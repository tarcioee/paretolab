# Web interface

```bash
paretolab ui experiment.yaml                          # opens http://127.0.0.1:8765/ in the browser
paretolab ui new.yaml --project project.yaml          # a new setup, created on the first save
paretolab ui experiment.yaml --port 9000 --no-browser
```

The interface is one more front end of the command line. It does not run anything itself:

- it writes `experiment.yaml`;
- it starts `paretolab run` and `paretolab analyze` as separate processes;
- it reads `state.json`, the run results and `analysis/summary.json`.

Closing the interface (Ctrl+C in its terminal) does not stop an experiment. An experiment started from a terminal shows up in the interface too, and can be paused from it.

## Tabs

| Tab | What it does |
|---|---|
| **Setup** | A form built from the project manifest: instances, algorithm variants, seeds, budget, parameters, tuning, indicators and statistics. Every change is validated by the server with the same code as `paretolab validate`. The panel on the side shows the errors, the number of runs, what will be tuned, and the YAML that will be saved. |
| **Run** | Start, pause and resume. It shows the progress, the time left, the tuning of each variant, a table of finished and failed runs per instance and variant, and the logs. |
| **Results** | The analysis: per indicator, the table of means, the mean ranks, Friedman, Nemenyi and Wilcoxon-Holm, and the figures. "Analyse now" analyses the runs finished so far. |
| **Project** | The manifest: objectives, instances, algorithms, parameters and the command of one run. It is edited in its own file. |

### Parameters in the form

Each algorithm has a table with one row per parameter. The columns are "all variants" (the key `algorithm` in the setup) and one column per variant (`algorithm/variant`, which wins).

- An empty cell uses the manifest default.
- With tuning enabled, an empty cell is **tuned**, and a value fixes the parameter, so it is not tuned.

## Saving

- The setup is saved only when it is valid, and not while the experiment is running.
- The previous file is kept as `experiment.yaml.bak`.
- The saved file contains only the values that differ from the defaults, in the order of the documentation. **Comments in the file are lost;** edit the file by hand if you want to keep them.

## Files

The screen output of the processes started by the interface goes to `<output_dir>/ui_run.log` and `<output_dir>/ui_analyze.log`. The Run tab shows them next to `paretolab.log`.

## Safety

- The interface listens on 127.0.0.1 only. It has no authentication: it is meant for one user on one machine.
- Requests whose `Host` or `Origin` is not that address are refused. This blocks other web sites and DNS rebinding.
- Changes need a JSON body, so a plain form on another site cannot post to it.
- Only files inside the output folder are served.
- On Windows, the port is taken exclusively; if it is in use, the next free port is used.

Two `paretolab run` on the same output folder are refused: the second one sees the first one's process in `state.json`.

## Dependencies

None beyond paretolab's own: the server is Python's `http.server`, and the page is plain HTML, CSS and JavaScript, with no build step and nothing loaded from the internet.
