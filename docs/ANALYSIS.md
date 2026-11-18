# Analysis

```bash
paretolab analyze experiment.yaml                  # reads <output_dir>/runs, writes <output_dir>/analysis
paretolab analyze experiment.yaml --runs-dir DIR   # analyse results stored elsewhere
paretolab analyze experiment.yaml --no-figures
```

Run results are read from `runs/<instance>/<algorithm>/<variant>/seed_<n>/result.json`. Only the runs planned by the setup are analysed. Planned runs without a result are reported as warnings.

## Indicators

**Multi-objective** indicators are computed per instance, with [moocore](https://github.com/multi-objective/moocore):

1. The fronts of all runs of the instance are joined. Runs with status `error` are left out.
2. Every objective is turned into minimization and min-max normalized with the bounds of that union. After this, 0 is the best value seen and 1 the worst.
3. The **reference set** is the non-dominated part of the normalized union.
4. The indicators are:
   - `hv`: hypervolume, with reference point `1 + reference_offset` in every objective (default 1.1). Higher is better.
   - `igd_plus`, `igd`, `epsilon_additive`: distance-based, measured against the reference set. Lower is better.

A run without feasible solutions gets `hv = 0`, and its distance-based indicators are left empty.

Because the bounds come from the runs being compared, indicator values from different analyses are not comparable with each other.

**Single-objective** indicators:

- `best`: the run's best value.
- `gap`: `100 * (best - optimum) / |optimum|`, with the sign flipped for maximization. When the optimum is 0, the absolute difference is used.

## Statistics

The settings are in `statistics` in the setup.

A **block** is one row of the tests. It can be:

- one instance, with its runs aggregated by `median` (default) or `mean`;
- one `(instance, seed)` pair, with `blocks: runs`. This needs the same seeds in every variant.

With a single instance, `instances` falls back to `runs`. Blocks where some variant has no value are dropped, and the drop is reported.

| Test | Output |
|---|---|
| Friedman (3 or more variants) | χ², p-value, mean ranks (1 = best) |
| Nemenyi | critical difference (Demšar, 2006) and pairwise p-values |
| Wilcoxon signed-rank, Holm-corrected | every pair: median difference, p, Holm-adjusted p, which variant is better |

The tests are fixed by the setup. paretolab never picks them from the data.

## Output (`<output_dir>/analysis`)

| File | Contents |
|---|---|
| `indicators_per_run.csv` | one row per run: identity, status, number of points, evaluations, time, indicators |
| `tables/<indicator>.{csv,md,tex}` | per instance and variant: mean, standard deviation, median, IQR. The best mean is in bold. |
| `statistics/<indicator>.json` | everything from the tests above |
| `figures/cd_<indicator>.png` | critical-difference diagram |
| `figures/box_<indicator>_<instance>.png` | boxplots per variant |
| `figures/attainment_<instance>.png` | median (50%) empirical attainment surface per variant. Biobjective only. |
| `figures/ecdf_<indicator>_<instance>.png` | ECDF of the final value. Single-objective only. |
| `figures/convergence_<instance>.png` | median best-so-far value against evaluations. Single-objective runs with a `convergence_trace` only. |
| `summary.json` | file paths, mean ranks, Friedman p-values, per-instance reference data, warnings |

Per-instance figures are made for the first 12 instances.
