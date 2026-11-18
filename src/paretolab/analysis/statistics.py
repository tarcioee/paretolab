"""Non-parametric comparison of the algorithm variants (Demsar, 2006).

* Friedman test on the ranks of the variants in each block, and the mean ranks;
* Nemenyi post-hoc test: critical difference (CD) of the mean ranks and pairwise p-values;
* Wilcoxon signed-rank test for every pair, with Holm's correction for multiple comparisons.

A block is one instance (its runs aggregated by median or mean) or one (instance, seed) pair.
"""
import itertools
import math

import numpy as np
import pandas as pd
import scikit_posthocs as sp
from scipy import stats


def block_matrix(df: pd.DataFrame, indicator: str, blocks: str, aggregation: str):
    """(blocks x units matrix, blocks mode actually used, warnings). Blocks with a missing value are dropped."""
    warnings = []
    data = df[df["status"] != "error"]
    if blocks == "instances" and data["instance"].nunique() < 2:
        blocks = "runs"
        warnings.append("only one instance: each (instance, seed) pair is a block")
    if blocks == "instances":
        matrix = data.pivot_table(index="instance", columns="unit", values=indicator, aggfunc=aggregation,
                                  dropna=False)
    else:
        matrix = data.pivot_table(index=["instance", "seed"], columns="unit", values=indicator, aggfunc="first",
                                  dropna=False)
    incomplete = matrix.isna().any(axis=1)
    if incomplete.any():
        warnings.append(f"{int(incomplete.sum())} of {len(matrix)} blocks dropped: some variant has no value "
                        f"(run missing, failed or without feasible solutions)")
        matrix = matrix[~incomplete]
    return matrix, blocks, warnings


def critical_difference(alpha: float, k: int, n: int) -> float:
    q = stats.studentized_range.ppf(1 - alpha, k, np.inf) / math.sqrt(2)
    return float(q * math.sqrt(k * (k + 1) / (6.0 * n)))


def holm(pvalues) -> np.ndarray:
    p = np.asarray(pvalues, dtype=float)
    order = np.argsort(p)
    adjusted = np.empty_like(p)
    running = 0.0
    for i, idx in enumerate(order):
        running = max(running, min(1.0, (len(p) - i) * p[idx]))
        adjusted[idx] = running
    return adjusted


def compare(df: pd.DataFrame, indicator: str, higher_is_better: bool, tests, alpha: float, blocks: str,
            aggregation: str) -> dict:
    matrix, blocks_used, warnings = block_matrix(df, indicator, blocks, aggregation)
    n, k = matrix.shape
    out = {"indicator": indicator, "higher_is_better": higher_is_better, "alpha": alpha, "blocks": blocks_used,
           "aggregation": aggregation if blocks_used == "instances" else None, "n_blocks": int(n),
           "units": list(matrix.columns), "warnings": warnings}
    if k < 2 or n < 2:
        out["warnings"].append("at least 2 variants and 2 complete blocks are needed for the tests")
        return out
    ranks = matrix.rank(axis=1, ascending=not higher_is_better, method="average")
    out["mean_ranks"] = {u: float(r) for u, r in ranks.mean().sort_values().items()}
    if n < 10:
        out["warnings"].append(f"only {n} blocks: the tests have little power (Demsar recommends more than 10)")

    if "friedman" in tests and k >= 3:
        if np.allclose(matrix.values, matrix.values[:, :1]):
            chi2, p = 0.0, 1.0
        else:
            chi2, p = stats.friedmanchisquare(*(matrix[c].values for c in matrix.columns))
        out["friedman"] = {"chi2": float(chi2), "df": k - 1, "p_value": float(p), "reject_h0": bool(p < alpha)}

    if "nemenyi" in tests and k >= 3:
        pvals = sp.posthoc_nemenyi_friedman(matrix.values)
        pvals.index = pvals.columns = list(matrix.columns)
        out["nemenyi"] = {"critical_difference": critical_difference(alpha, k, n),
                          "p_values": {a: {b: float(pvals.loc[a, b]) for b in matrix.columns} for a in matrix.columns}}

    if "wilcoxon_holm" in tests:
        pairs = []
        for a, b in itertools.combinations(matrix.columns, 2):
            diff = matrix[a].values - matrix[b].values
            if np.allclose(diff, 0):
                stat, p = 0.0, 1.0
            else:
                stat, p = stats.wilcoxon(matrix[a].values, matrix[b].values)
            median = float(np.median(diff))
            better = None if median == 0 else (a if (median > 0) == higher_is_better else b)
            pairs.append({"a": a, "b": b, "median_difference": median, "statistic": float(stat),
                          "p_value": float(p), "better": better})
        for pair, adjusted in zip(pairs, holm([q["p_value"] for q in pairs]), strict=True):
            pair["p_holm"] = float(adjusted)
            pair["significant"] = bool(adjusted < alpha)
        out["wilcoxon_holm"] = pairs
    return out
