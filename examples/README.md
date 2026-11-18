# Examples

Each folder holds a project (`project.yaml`), an experiment (`experiment.yaml`) and the program that runs one execution. Run from the folder:

```bash
paretolab run experiment.yaml      # runs, then analyses into results/analysis
paretolab ui experiment.yaml       # or follow it in the web interface
```

| Example | Language | Objectives | What it shows |
|---|---|---|---|
| [tsp](tsp) | Python | 1 (tour length) | Iterated local search on burma14 and gr17 from TSPLIB, whose optimal lengths are known (3323 and 2085): the `gap` indicator, convergence curves, two variants and two parameters. About 5 s. |
| [zdt1](zdt1) | Python | 2 | A small NSGA-II against random search on ZDT1, with the hypervolume and IGD+. About 6 s. |
| [dtlz2](dtlz2) | C++ | 3 | A (1+1) evolution strategy with a Pareto archive against random search on DTLZ2. Build it first: `g++ -O2 -std=c++17 dtlz2.cpp -o dtlz2`. About 4 s. |

Python programs are started with `{python}`, the interpreter running paretolab, so they work the same on Windows and Linux. The C++ program is `executable: ./dtlz2`; on Windows, `dtlz2.exe` is found as well.

The checks in `tests/test_examples.py` run every example on a small budget. They check the TSP data against the published optima, computed exactly by Held-Karp in `tsp/tsplib.py`. They also check that no ZDT1 point lies below the true front, and that every DTLZ2 point lies on or outside the unit sphere.

The TSPLIB instances are from Reinelt's TSPLIB, which is distributed for research use.
