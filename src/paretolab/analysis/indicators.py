"""Quality indicators of every run.

Multi-objective (per instance, with moocore):

1. the fronts of all non-error runs of the instance are joined;
2. each objective is turned into minimization and min-max normalized to [0, 1] with the bounds of that union
   (0 = best value seen, 1 = worst);
3. the reference set is the non-dominated part of the normalized union;
4. HV uses the reference point (1 + offset, ..., 1 + offset); IGD, IGD+ and additive epsilon use the reference set.

A run without feasible solutions gets HV = 0 and no value (NaN) for the distance-based indicators.

Single-objective: ``best`` is the best value of the run (in the objective's sense) and ``gap`` its relative
distance to the instance's known optimum, in percent (absolute distance when the optimum is 0).
"""
from dataclasses import dataclass, field

import moocore
import numpy as np
import pandas as pd

from paretolab.contract import Manifest, RunResult

LABELS = {"hv": "Hypervolume", "igd_plus": "IGD+", "igd": "IGD", "epsilon_additive": "Additive epsilon",
          "best": "Best value", "gap": "Gap to optimum (%)"}
_DISTANCE = {"igd_plus": moocore.igd_plus, "igd": moocore.igd, "epsilon_additive": moocore.epsilon_additive}


def higher_is_better(indicator: str, manifest: Manifest) -> bool:
    if indicator == "best":
        return manifest.objectives[0].sense == "max"
    return indicator == "hv"


def unit_label(algorithm: str, variant: str) -> str:
    return algorithm if variant == "default" else f"{algorithm}/{variant}"


@dataclass
class Normalizer:
    """Min-max normalization to [0, 1] after turning every objective into minimization."""

    maximise: np.ndarray
    lower: np.ndarray
    span: np.ndarray

    @classmethod
    def fit(cls, fronts: list, maximise: np.ndarray) -> "Normalizer":
        union = np.vstack([np.where(maximise, -f, f) for f in fronts])
        lower, upper = union.min(axis=0), union.max(axis=0)
        return cls(maximise, lower, np.where(upper > lower, upper - lower, 1.0))

    def __call__(self, front) -> np.ndarray:
        front = np.asarray(front, dtype=float).reshape(-1, len(self.maximise))
        return (np.where(self.maximise, -front, front) - self.lower) / self.span


@dataclass
class InstanceReference:
    instance: str
    normalizer: Normalizer = None
    reference_set: np.ndarray = None          # normalized, minimization
    hv_reference: float = float("nan")
    runs_used: int = 0
    notes: list = field(default_factory=list)


def compute(runs: list[RunResult], manifest: Manifest, indicators: list[str],
            reference_offset: float = 0.1) -> tuple[pd.DataFrame, dict]:
    """One row per run with its indicators, and the per-instance references used (multi-objective only)."""
    rows, references = [], {}
    maximise = np.array([o.sense == "max" for o in manifest.objectives])
    for instance in sorted({r.instance for r in runs}):
        group = [r for r in runs if r.instance == instance]
        if manifest.is_multiobjective:
            ref = _multi_reference(instance, group, maximise)
            references[instance] = ref
            values = [_multi_values(r, ref, indicators, reference_offset) for r in group]
        else:
            optimum = manifest.instance(instance).optimum if instance in {i.name for i in manifest.instances} else None
            values = [_single_values(r, manifest.objectives[0].sense, optimum, indicators) for r in group]
        for run, vals in zip(group, values, strict=True):
            rows.append({"instance": run.instance, "algorithm": run.algorithm, "variant": run.variant,
                         "unit": unit_label(run.algorithm, run.variant), "seed": run.seed, "status": run.status,
                         "points": len(run.front), "evaluations": run.evaluations, "wall_time_s": run.wall_time_s,
                         **vals})
    columns = ["instance", "algorithm", "variant", "unit", "seed", "status", "points", "evaluations",
               "wall_time_s", *indicators]
    return pd.DataFrame(rows, columns=columns), references


def _multi_reference(instance, group, maximise) -> InstanceReference:
    ref = InstanceReference(instance)
    fronts = [np.asarray(r.front, dtype=float) for r in group if r.status != "error" and r.front]
    ref.runs_used = len(fronts)
    if not fronts:
        ref.notes.append("no run of this instance has feasible solutions")
        return ref
    ref.normalizer = Normalizer.fit(fronts, maximise)
    ref.reference_set = moocore.filter_dominated(np.vstack([ref.normalizer(f) for f in fronts]))
    return ref


def _multi_values(run, ref: InstanceReference, indicators, offset) -> dict:
    values = dict.fromkeys(indicators, float("nan"))
    if run.status == "error" or ref.normalizer is None:
        return values
    point = np.full(len(ref.normalizer.maximise), 1.0 + offset)
    if np.isnan(ref.hv_reference):
        ref.hv_reference = float(moocore.hypervolume(ref.reference_set, ref=point))
    if not run.front:
        if "hv" in values:
            values["hv"] = 0.0
        return values
    front = ref.normalizer(run.front)
    for name in indicators:
        if name == "hv":
            values[name] = float(moocore.hypervolume(front, ref=point))
        else:
            values[name] = float(_DISTANCE[name](front, ref=ref.reference_set))
    return values


def _single_values(run, sense, optimum, indicators) -> dict:
    values = dict.fromkeys(indicators, float("nan"))
    if run.status == "error" or not run.front:
        return values
    column = [p[0] for p in run.front]
    best = max(column) if sense == "max" else min(column)
    if "best" in values:
        values["best"] = best
    if "gap" in values and optimum is not None:
        distance = (optimum - best) if sense == "max" else (best - optimum)
        values["gap"] = 100.0 * distance / abs(optimum) if optimum != 0 else distance
    return values
