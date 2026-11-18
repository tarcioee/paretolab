"""The examples in examples/: each one runs end to end on a small budget, and its results are checked against
what is known about the problem (TSP optima, the ZDT1 and DTLZ2 fronts)."""
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from paretolab.analysis import analyze
from paretolab.contract import RunResult
from paretolab.contract.layout import result_files
from paretolab.execution import EXIT_OK, Runner

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def copy_example(name, tmp_path, **setup):
    folder = tmp_path / name
    shutil.copytree(EXAMPLES / name, folder, ignore=shutil.ignore_patterns("results", "dtlz2", "dtlz2.exe"))
    data = yaml.safe_load((folder / "experiment.yaml").read_text(encoding="utf-8"))
    data.update(setup)
    (folder / "experiment.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return folder


def run(folder) -> dict:
    assert Runner(folder / "experiment.yaml", log=lambda *_: None).run() == EXIT_OK
    out = {}
    for path in result_files(folder / "results" / "runs"):
        r = RunResult.model_validate_json(path.read_text(encoding="utf-8"))
        assert r.status == "ok", r.error_message
        out[(r.instance, r.algorithm, r.variant, r.seed)] = r
    return out


def test_tsp_instances_match_the_published_optima():
    sys.path.insert(0, str(EXAMPLES / "tsp"))
    try:
        import tsplib
    finally:
        sys.path.pop(0)
    project = yaml.safe_load((EXAMPLES / "tsp" / "project.yaml").read_text(encoding="utf-8"))
    for instance in project["instances"]:
        d = tsplib.read(EXAMPLES / "tsp" / instance["path"])
        assert tsplib.held_karp(d) == instance["optimum"]


def test_tsp_example(tmp_path):
    folder = copy_example("tsp", tmp_path, seeds={"count": 4})
    results = run(folder)
    assert len(results) == 16
    optimum = {"burma14": 3323, "gr17": 2085}
    for (instance, _, _, _), r in results.items():
        assert r.front[0][0] >= optimum[instance]                       # never better than the optimum
        tour = r.variables[0]
        assert sorted(tour) == list(range(len(tour)))                    # a permutation of the cities
    assert min(r.front[0][0] for k, r in results.items() if k[0] == "burma14" and k[2] == "two_opt") == 3323
    summary = analyze(folder / "experiment.yaml", figures=False, log=lambda *_: None)
    assert set(summary["indicators"]) == {"best", "gap"}


def test_zdt1_example(tmp_path):
    folder = copy_example("zdt1", tmp_path, seeds={"count": 3}, budget={"max_evaluations": 4000})
    results = run(folder)
    for r in results.values():
        assert all(f2 >= 1 - math.sqrt(f1) - 1e-12 for f1, f2 in r.front)    # on or above the true front
    analyze(folder / "experiment.yaml", figures=False, log=lambda *_: None)
    table = (folder / "results" / "analysis" / "indicators_per_run.csv").read_text(encoding="utf-8").splitlines()
    rows = [dict(zip(table[0].split(","), line.split(","), strict=True)) for line in table[1:]]
    hv = {(r["unit"], r["seed"]): float(r["hv"]) for r in rows}
    assert all(hv[("nsga2", s)] > hv[("random", s)] for s in ("1", "2", "3"))


def find_compiler():
    found = shutil.which("g++")
    if not found and os.name == "nt" and Path(r"C:\msys64\mingw64\bin\g++.exe").is_file():
        found = r"C:\msys64\mingw64\bin\g++.exe"
    return found


@pytest.mark.skipif(not find_compiler(), reason="no C++ compiler")
def test_dtlz2_example(tmp_path):
    folder = copy_example("dtlz2", tmp_path, seeds={"count": 3}, budget={"max_evaluations": 5000})
    compiler = find_compiler()
    env = dict(os.environ, PATH=str(Path(compiler).parent) + os.pathsep + os.environ.get("PATH", ""))
    flags = ["-static"] if os.name == "nt" else []      # no dependency on the compiler's DLLs
    subprocess.run([compiler, "-O2", "-std=c++17", *flags, "dtlz2.cpp", "-o", "dtlz2"], cwd=folder, check=True,
                   env=env)
    results = run(folder)
    assert len(results) == 6
    for r in results.values():
        assert r.front and all(sum(v * v for v in p) >= 1 - 1e-9 for p in r.front)   # on or outside the sphere
        assert r.evaluations == 5000
    summary = analyze(folder / "experiment.yaml", figures=False, log=lambda *_: None)
    assert summary["indicators"]["hv"]["mean_ranks"]["paes"] < summary["indicators"]["hv"]["mean_ranks"]["random"]
    assert json.loads((folder / "results" / "analysis" / "summary.json").read_text())["runs_analysed"] == 6
