"""Figures of the analysis (matplotlib, files only, no window)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import moocore
import numpy as np

from paretolab.analysis.indicators import LABELS

DPI = 150


def _save(fig, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def boxplot(df, indicator, instance, path):
    data = df[(df["instance"] == instance) & df[indicator].notna()]
    units = sorted(data["unit"].unique())
    fig, ax = plt.subplots(figsize=(max(4, 1.1 * len(units) + 2), 4))
    ax.boxplot([data.loc[data["unit"] == u, indicator].values for u in units], showmeans=True)
    ax.set_xticks(range(1, len(units) + 1), units, rotation=30, ha="right")
    ax.set_ylabel(LABELS.get(indicator, indicator))
    ax.set_title(f"{LABELS.get(indicator, indicator)}, instance {instance}")
    ax.grid(axis="y", alpha=0.3)
    return _save(fig, path)


def cd_diagram(mean_ranks: dict, cd: float, title: str, path):
    """Demsar-style diagram: mean ranks on an axis (1 = best); a bar joins variants closer than the CD."""
    units = list(mean_ranks)
    ranks = np.array([mean_ranks[u] for u in units])
    k = len(units)
    order = np.argsort(ranks)
    groups, sorted_ranks = [], ranks[order]
    for i in range(k):
        j = max(j for j in range(i, k) if sorted_ranks[j] - sorted_ranks[i] < cd)
        if j > i and not any(g[0] <= i and j <= g[1] for g in groups):
            groups.append((i, j))
    first_label = 0.6 + 0.3 * len(groups)
    fig, ax = plt.subplots(figsize=(7, 1.4 + 0.3 * (k + len(groups))))
    ax.set_xlim(0.5, k + 0.5)
    ax.set_ylim(-(first_label + k), 2.5)
    ax.invert_xaxis()
    ax.axis("off")
    ax.hlines(0, 1, k, color="black")
    for t in range(1, k + 1):
        ax.vlines(t, 0, 0.25, color="black")
        ax.text(t, 0.45, str(t), ha="center", va="bottom", fontsize=9)
    ax.hlines(1.6, 1, 1 + cd, color="black", linewidth=2)
    ax.text(1 + cd / 2, 1.8, f"CD = {cd:.2f}", ha="center", va="bottom", fontsize=9)
    for n, (i, j) in enumerate(groups):
        y = -0.35 - 0.3 * n
        ax.hlines(y, sorted_ranks[i] - 0.03, sorted_ranks[j] + 0.03, color="black", linewidth=3)
    for line, idx in enumerate(order):
        y = -(first_label + line)
        ax.vlines(ranks[idx], y, 0, color="gray", linewidth=0.8, zorder=0)
        ax.text(ranks[idx], y, f" {units[idx]} ({ranks[idx]:.2f}) ", va="center",
                ha="right" if line < (k + 1) // 2 else "left", fontsize=9)
    ax.set_title(title, fontsize=10)
    return _save(fig, path)


def _staircase(points, maximise):
    """Sorted step line of a biobjective non-dominated set (original units)."""
    order = np.argsort(points[:, 0] * (-1 if maximise[0] else 1))
    return points[order]


def attainment(runs_by_unit: dict, objectives, instance, path, percentile=50):
    """Median (by default) empirical attainment surface of each variant; biobjective only."""
    maximise = np.array([o.sense == "max" for o in objectives])
    sign = np.where(maximise, -1.0, 1.0)
    fig, ax = plt.subplots(figsize=(6, 4.5))
    for unit, fronts in sorted(runs_by_unit.items()):
        fronts = [np.asarray(f, dtype=float) for f in fronts if f]
        if not fronts:
            continue
        points = np.vstack(fronts) * sign
        sets = np.concatenate([np.full(len(f), i + 1) for i, f in enumerate(fronts)])
        surface = moocore.eaf(points, sets=sets, percentiles=[percentile])
        if len(surface):
            line = _staircase(surface[:, :2] * sign, maximise)
            ax.step(line[:, 0], line[:, 1], where="post", label=unit, marker=".", markersize=3)
    ax.set_xlabel(_axis_label(objectives[0]))
    ax.set_ylabel(_axis_label(objectives[1]))
    ax.set_title(f"{percentile}% attainment surface, instance {instance}")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    return _save(fig, path)


def quality_ecdf(df, indicator, instance, path):
    """Single-objective: fraction of runs whose final value is at least as good as x."""
    data = df[(df["instance"] == instance) & df[indicator].notna()]
    fig, ax = plt.subplots(figsize=(6, 4))
    for unit in sorted(data["unit"].unique()):
        values = np.sort(data.loc[data["unit"] == unit, indicator].values)
        ax.step(values, np.arange(1, len(values) + 1) / len(values), where="post", label=unit)
    ax.set_xlabel(LABELS.get(indicator, indicator))
    ax.set_ylabel("fraction of runs")
    ax.set_title(f"ECDF of the final {LABELS.get(indicator, indicator).lower()}, instance {instance}")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    return _save(fig, path)


def convergence(traces_by_unit: dict, objective, instance, path):
    """Single-objective: median best-so-far value against evaluations (runs with a convergence trace)."""
    fig, ax = plt.subplots(figsize=(6, 4))
    pick = max if objective.sense == "max" else min
    for unit, traces in sorted(traces_by_unit.items()):
        curves = [[(t.evaluations, pick(p[0] for p in t.front)) for t in trace if t.evaluations is not None and t.front]
                  for trace in traces]
        curves = [c for c in curves if c]
        if not curves:
            continue
        grid = np.unique(np.concatenate([[e for e, _ in c] for c in curves]))
        sampled = []
        for c in curves:
            evals, values = np.array([e for e, _ in c]), np.array([v for _, v in c])
            idx = np.searchsorted(evals, grid, side="right") - 1
            sampled.append(np.where(idx >= 0, values[np.clip(idx, 0, None)], np.nan))
        ax.plot(grid, np.nanmedian(np.vstack(sampled), axis=0), label=f"{unit} ({len(curves)} runs)")
    ax.set_xlabel("evaluations")
    ax.set_ylabel(_axis_label(objective))
    ax.set_title(f"Median convergence, instance {instance}")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    return _save(fig, path)


def _axis_label(objective):
    unit = f" [{objective.unit}]" if objective.unit else ""
    return f"{objective.name}{unit} ({objective.sense})"
