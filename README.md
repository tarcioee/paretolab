# paretolab

*[Leia em português](README.pt-BR.md)*

**Problem-agnostic experiment manager for single- and multi-objective optimization.**

You bring your problem and your algorithms. They can be written in any language, because paretolab runs them through a command-line contract. paretolab takes care of everything else in the experimental pipeline:

- **Tuning:** with irace, per algorithm and variant.
- **Execution:** parallel runs with a time limit per run.
- **Pause and resume:** at any point, including in the middle of tuning.
- **Indicators:** hypervolume and IGD+ for multi-objective runs, gap to the optimum for single-objective runs. They are computed with [moocore](https://github.com/multi-objective/moocore).
- **Statistics:** Friedman, Nemenyi and Wilcoxon-Holm, plus critical-difference diagrams.
- **Reports:** tables, plots and a local web interface.

> **Status: pre-alpha (0.x).** The API, the file formats and the names may change without notice. See the [roadmap](docs/ROADMAP.md).

## Install

```bash
pip install git+https://github.com/tarcioee/paretolab
paretolab doctor
```

## Use

```bash
paretolab validate project.yaml          # describe your problem: docs/CONTRACT.md
paretolab validate experiment.yaml       # choose what to run
paretolab run experiment.yaml            # tune (if enabled), run or resume, then analyse: docs/EXECUTION.md
paretolab pause experiment.yaml          # or Ctrl+C; `run` again to continue
paretolab analyze experiment.yaml        # indicators, tests, tables and figures: docs/ANALYSIS.md
paretolab ui experiment.yaml             # all of the above from a local web page: docs/WEB.md
```

Worked examples (TSP, ZDT1, DTLZ2) are in [examples/](examples).

Tuning also needs R with the `irace` package; see [docs/TUNING.md](docs/TUNING.md).

## License

[Mozilla Public License 2.0](LICENSE).

- **Using paretolab:** anyone can use it, for any purpose.
- **Modifying paretolab:** changes to paretolab's own files must stay open when you distribute them.
- **Your own code:** your algorithms and plugins can use any license.
