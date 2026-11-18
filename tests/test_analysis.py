import json
import math

import numpy as np
import pandas as pd
import pytest
import yaml

from paretolab.analysis import analyze
from paretolab.analysis import indicators as ind
from paretolab.analysis.statistics import compare, critical_difference, holm
from paretolab.contract import Manifest, RunResult, write_result
from paretolab.contract.layout import run_dir


def run(manifest, instance, unit, seed, front, status="ok"):
    algorithm, _, variant = unit.partition("/")
    return RunResult(instance=instance, algorithm=algorithm, variant=variant or "default", seed=seed,
                     objectives=manifest.objectives, front=front, status=status)


# ---------- indicators ----------

def test_multiobjective_normalization_and_hv(biobjective):
    m = Manifest.model_validate(biobjective)          # power (max), cost (min)
    runs = [run(m, "A", "mosa/seq", 1, [[10, 0], [0, -10]]),   # ideal corner of the union
            run(m, "A", "mots", 1, [[0, 0]]),                  # nadir corner
            run(m, "A", "mots", 2, []),                        # no feasible solution
            run(m, "A", "mosa/ext", 1, [[5, 5]], status="error")]
    df, refs = ind.compute(runs, m, ["hv", "igd_plus"], reference_offset=0.1)
    hv = dict(zip(zip(df["unit"], df["seed"], strict=True), df["hv"], strict=True))
    # normalized (min-oriented): (10,0)->(0,1), (0,-10)->(1,0), (0,0)->(1,1); ref point (1.1, 1.1)
    assert hv[("mosa/seq", 1)] == pytest.approx(1.1 * 0.1 + 0.1 * 1.0)
    assert hv[("mots", 1)] == pytest.approx(0.01)
    assert hv[("mots", 2)] == 0.0
    assert math.isnan(hv[("mosa/ext", 1)])
    igd = df.set_index(["unit", "seed"])["igd_plus"]
    assert igd[("mosa/seq", 1)] == pytest.approx(0.0)
    assert math.isnan(igd[("mots", 2)])
    assert refs["A"].runs_used == 2 and len(refs["A"].reference_set) == 2


def test_hv_matches_a_direct_2d_computation(biobjective):
    rng = np.random.default_rng(0)
    m = Manifest.model_validate(biobjective)
    runs = [run(m, "A", "mots", s, rng.uniform(0, 100, size=(15, 2)).tolist()) for s in range(1, 6)]
    df, refs = ind.compute(runs, m, ["hv"], reference_offset=0.1)
    norm = refs["A"].normalizer
    for r, value in zip(runs, df["hv"], strict=True):
        pts = norm(r.front)
        pts = pts[np.argsort(pts[:, 0])]
        area, best_y = 0.0, 1.1
        for i, (x, y) in enumerate(pts):          # sweep over x; strips up to the next point (or the ref point)
            best_y = min(best_y, y)
            next_x = pts[i + 1, 0] if i + 1 < len(pts) else 1.1
            area += (next_x - x) * (1.1 - best_y)
        assert value == pytest.approx(area)


def test_single_objective_best_and_gap(tsp):
    m = Manifest.model_validate(tsp)
    runs = [run(m, "burma14", "ils", 1, [[3500.0]]), run(m, "burma14", "ils", 2, [[3323.0]]),
            run(m, "burma14", "ils", 3, [])]
    df, _ = ind.compute(runs, m, ["best", "gap"])
    assert df["best"].tolist()[:2] == [3500.0, 3323.0]
    assert df["gap"].tolist()[:2] == pytest.approx([100 * 177 / 3323, 0.0])
    assert df["gap"].isna().tolist()[2]
    assert ind.higher_is_better("best", m) is False


# ---------- statistics ----------

def test_holm_and_critical_difference():
    assert holm([0.01, 0.04, 0.03]).tolist() == pytest.approx([0.03, 0.06, 0.06])
    assert critical_difference(0.05, 3, 10) == pytest.approx(2.343 * math.sqrt(12 / 60), rel=1e-3)


def frame(values: dict) -> pd.DataFrame:
    """values: {unit: [one value per instance]} -> rows like indicators.compute."""
    rows = [{"instance": f"I{i}", "unit": u, "seed": 1, "status": "ok", "hv": v}
            for u, vs in values.items() for i, v in enumerate(vs)]
    return pd.DataFrame(rows)


def test_compare_ranks_and_tests():
    df = frame({"a": [0.9 + i / 100 for i in range(12)], "b": [0.5 + i / 100 for i in range(12)],
                "c": [0.1 + i / 100 for i in range(12)]})
    out = compare(df, "hv", True, ["friedman", "nemenyi", "wilcoxon_holm"], 0.05, "instances", "median")
    assert out["mean_ranks"] == {"a": 1.0, "b": 2.0, "c": 3.0}
    assert out["friedman"]["reject_h0"]
    assert out["nemenyi"]["p_values"]["a"]["c"] < 0.05
    pair = next(p for p in out["wilcoxon_holm"] if (p["a"], p["b"]) == ("a", "c"))
    assert pair["better"] == "a" and pair["significant"]


def test_compare_lower_is_better_and_ties():
    df = frame({"a": [1.0] * 12, "b": [2.0] * 12})
    out = compare(df, "hv", False, ["friedman", "wilcoxon_holm"], 0.05, "instances", "median")
    assert out["mean_ranks"] == {"a": 1.0, "b": 2.0}
    assert "friedman" not in out                                  # needs 3 or more variants
    assert out["wilcoxon_holm"][0]["better"] == "a"
    same = compare(frame({"a": [1.0] * 12, "b": [1.0] * 12, "c": [1.0] * 12}), "hv", True, ["friedman"], 0.05,
                   "instances", "median")
    assert same["friedman"]["p_value"] == 1.0


def test_single_instance_falls_back_to_runs_and_drops_incomplete_blocks():
    rows = [{"instance": "I", "unit": u, "seed": s, "status": "ok", "hv": (np.nan if (u, s) == ("b", 3) else s)}
            for u in "ab" for s in range(1, 6)]
    out = compare(pd.DataFrame(rows), "hv", True, ["wilcoxon_holm"], 0.05, "instances", "median")
    assert out["blocks"] == "runs" and out["n_blocks"] == 4
    assert any("one instance" in w for w in out["warnings"]) and any("dropped" in w for w in out["warnings"])


# ---------- end to end ----------

def test_analyze_end_to_end(tmp_path, biobjective):
    m = Manifest.model_validate(biobjective)
    (tmp_path / "project.yaml").write_text(yaml.safe_dump(biobjective), encoding="utf-8")
    (tmp_path / "experiment.yaml").write_text(yaml.safe_dump(
        {"output_dir": "out", "seeds": {"count": 4}, "budget": {"max_evaluations": 10}}), encoding="utf-8")
    rng = np.random.default_rng(1)
    for instance in ("A", "B"):
        for algorithm, variant in (("mosa", "seq"), ("mosa", "ext"), ("mots", "default")):
            for seed in range(1, 5):
                shift = {"seq": 0, "ext": 30, "default": 60}[variant]
                front = np.column_stack([rng.uniform(50, 100, 6) - shift, rng.uniform(0, 50, 6) + shift])
                write_result(run_dir(tmp_path / "out" / "runs", instance, algorithm, variant, seed) / "result.json",
                             run(m, instance, f"{algorithm}/{variant}", seed, front.tolist()))
    summary = analyze(tmp_path / "experiment.yaml", log=lambda *_: None)
    assert summary["runs_analysed"] == 24 and summary["runs_planned"] == 24
    assert set(summary["indicators"]) == {"hv", "igd_plus"}
    assert next(iter(summary["indicators"]["hv"]["mean_ranks"])) == "mosa/seq"
    out = tmp_path / "out" / "analysis"
    assert (out / "indicators_per_run.csv").exists() and (out / "tables" / "hv.tex").exists()
    assert (out / "figures" / "cd_hv.png").exists() and (out / "figures" / "attainment_A.png").exists()
    assert json.loads((out / "statistics" / "hv.json").read_text())["n_blocks"] == 2


def test_analyze_single_objective_with_traces(tmp_path, tsp):
    m = Manifest.model_validate(tsp)
    tsp["algorithms"] = [{"name": "ils"}, {"name": "sa"}, {"name": "rs"}]
    (tmp_path / "project.yaml").write_text(yaml.safe_dump(tsp), encoding="utf-8")
    (tmp_path / "experiment.yaml").write_text(yaml.safe_dump(
        {"output_dir": "out", "seeds": {"count": 3}, "budget": {"max_evaluations": 100}}), encoding="utf-8")
    for instance, opt in (("burma14", 3323), ("gr17", 2085)):
        for k, algorithm in enumerate(("ils", "sa", "rs")):
            for seed in range(1, 4):
                final = opt * (1 + 0.05 * k) + seed
                trace = [{"evaluations": e, "front": [[final + (100 - e)]]} for e in (10, 50, 100)]
                result = RunResult(instance=instance, algorithm=algorithm, variant="default", seed=seed,
                                   objectives=m.objectives, front=[[final]], convergence_trace=trace)
                write_result(run_dir(tmp_path / "out" / "runs", instance, algorithm, "default", seed)
                             / "result.json", result)
    summary = analyze(tmp_path / "experiment.yaml", log=lambda *_: None)
    assert set(summary["indicators"]) == {"best", "gap"}
    assert list(summary["indicators"]["gap"]["mean_ranks"]) == ["ils", "sa", "rs"]
    figures = tmp_path / "out" / "analysis" / "figures"
    assert (figures / "ecdf_gap_gr17.png").exists() and (figures / "convergence_burma14.png").exists()
