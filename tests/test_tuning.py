import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

from paretolab.contract import ContractError, Manifest, Parameter, RunOutput, RunResult, load_experiment
from paretolab.contract.layout import result_files
from paretolab.execution import EXIT_ERROR, EXIT_OK, Runner
from paretolab.execution.state import PAUSE_FILE, read_state
from paretolab.tuning import TuningUnit
from paretolab.tuning import rscript as r
from paretolab.tuning.base import value_from_text
from paretolab.tuning.irace import IraceTuner, best_from_output
from paretolab.tuning.target import EMPTY_COST, ENV_VAR, cost

HERE = Path(__file__).parent
SOLVER = str(HERE / "tune_solver.py")
FAKE_IRACE = str(HERE / "fake_irace.py")
PARAMETERS = [{"name": "x", "type": "real", "range": [0, 1], "default": 0.1},
              {"name": "k", "type": "integer", "range": [1, 5], "default": 1},
              {"name": "op", "type": "categorical", "values": ["a", "b"], "default": "a"}]


def make_experiment(tmp_path, mode="multi", tuning=None, **setup_extra):
    objectives = ([{"name": "cost", "sense": "min"}, {"name": "power", "sense": "max"}] if mode == "multi"
                  else [{"name": "length", "sense": "min"}])
    project = {"name": "toy", "objectives": objectives, "instances": ["i1", "i2"],
               "algorithms": [{"name": "toy", "parameters": PARAMETERS}],
               "command": [sys.executable, SOLVER, mode, "{seed}", "{result_file}", "{params}"]}
    setup = {"output_dir": "out", "seeds": {"count": 2}, "budget": {"max_evaluations": 10}, "parallel_jobs": 2,
             "tuning": {"enabled": True, "max_experiments": 100, **(tuning or {})}, **setup_extra}
    (tmp_path / "project.yaml").write_text(yaml.safe_dump(project), encoding="utf-8")
    (tmp_path / "experiment.yaml").write_text(yaml.safe_dump(setup), encoding="utf-8")
    return tmp_path / "experiment.yaml"


@pytest.fixture
def fake_irace(monkeypatch):
    """irace replaced by tests/fake_irace.py: no R needed."""
    monkeypatch.setattr(IraceTuner, "check", lambda self: "irace (fake)")
    monkeypatch.setattr(IraceTuner, "command", lambda self, unit: [sys.executable, FAKE_IRACE])


def quiet(*_):
    pass


def unit_folder(tmp_path):
    return tmp_path / "out" / "tuning" / "toy" / "default"


def run_params(tmp_path) -> list:
    return [RunResult.model_validate_json(p.read_text(encoding="utf-8")).parameters
            for p in result_files(tmp_path / "out" / "runs")]


# ---------------------------------------------------------------------------------------------- pieces

def test_value_from_text():
    real = Parameter(name="t", type="real", range=(0.1, 10))
    integer = Parameter(name="k", type="integer", range=(1, 5))
    cat = Parameter(name="op", type="categorical", values=["swap", 2, True])
    assert value_from_text(real, "2.5") == 2.5
    assert value_from_text(integer, "3") == 3 and isinstance(value_from_text(integer, "3.0"), int)
    assert value_from_text(cat, '"swap"') == "swap" and value_from_text(cat, "2") == 2
    assert value_from_text(cat, "true") is True
    for p, text in ((real, "20"), (integer, "0"), (cat, "insert")):
        with pytest.raises(ValueError):
            value_from_text(p, text)


def test_irace_input_files(tmp_path):
    params = [Parameter(name="t0", type="real", range=(0.01, 100), log=True),
              Parameter(name="k", type="integer", range=(1, 10)),
              Parameter(name="move", type="categorical", values=["2opt", "oropt"]),
              Parameter(name="alpha", type="real", range=(0, 1), condition='move == "oropt"')]
    unit = TuningUnit(algorithm="ils", variant="default", folder=tmp_path, parameters=params,
                      defaults={"k": 3}, instances=["a", "b"], max_experiments=500, jobs=3, seed=7,
                      target_config=tmp_path / "target.json")
    tuner = IraceTuner()
    text = tuner.parameters_text(unit)
    assert 't0 "--t0=" r,log (0.01, 100)' in text
    assert 'k "--k=" i (1, 10)' in text
    assert 'move "--move=" c ("2opt", "oropt")' in text
    assert 'alpha "--alpha=" r (0, 1) | move == "oropt"' in text
    assert tuner.default_configuration(unit) is None          # incomplete and conditional
    tuner.write_inputs(unit, recover=True)
    scenario = (tmp_path / "scenario.txt").read_text()
    assert "maxExperiments = 500" in scenario and "parallel = 3" in scenario and "seed = 7" in scenario
    assert "recoveryFile" in scenario and "configurationsFile" not in scenario
    assert (tmp_path / "instances.txt").read_text().split() == ["a", "b"]

    simple = TuningUnit(algorithm="ils", variant="default", folder=tmp_path, parameters=params[:3],
                        defaults={"t0": 1.0, "k": 3, "move": "2opt"}, instances=["a"], max_experiments=100,
                        jobs=1, seed=1, target_config=tmp_path / "target.json")
    assert tuner.default_configuration(simple) == "t0 k move\n1 3 2opt\n"


def test_categorical_values_irace_cannot_read(tmp_path):
    from paretolab.tuning import TuningFailed

    unit = TuningUnit(algorithm="a", variant="default", folder=tmp_path, defaults={}, instances=["i"],
                      parameters=[Parameter(name="op", type="categorical", values=["two words", "x"])],
                      max_experiments=10, jobs=1, seed=1, target_config=tmp_path / "t.json")
    with pytest.raises(TuningFailed, match="two words"):
        IraceTuner().parameters_text(unit)


def test_best_from_output_takes_the_last_block():
    text = ("# Best configurations as commandlines (first number is the configuration ID)\n"
            "3  --x=0.1 --op=a\n...\n"
            "# Best configurations as commandlines (first number is the configuration ID)\n"
            "12  --x=0.6967 --k=3 --op=b\n13  --x=0.5 --k=2 --op=b\n")
    assert best_from_output(text) == {"x": "0.6967", "k": "3", "op": "b"}
    assert best_from_output("nothing here") == {}


def test_cost():
    single = Manifest(name="s", objectives=[{"name": "f", "sense": "max"}], instances=["i"],
                      algorithms=[{"name": "a"}], command=["x", "{seed}", "{result_file}"])
    assert cost(RunOutput(front=[[3.0], [5.0]]), single) == -5.0
    assert cost(RunOutput(front=[]), single) == EMPTY_COST
    multi = Manifest(name="m", objectives=[{"name": "f", "sense": "min"}, {"name": "g", "sense": "max"}],
                     instances=["i"], algorithms=[{"name": "a"}], command=["x", "{seed}", "{result_file}"])
    bounds = [[0, 10], [0, 100]]                     # f in [0, 10] (min), g in [0, 100] (max)
    best_point = RunOutput(front=[[0.0, 100.0]])     # normalized (0, 0): HV up to (1.1, 1.1)
    assert cost(best_point, multi, bounds, 0.1) == pytest.approx(-1.21)
    assert cost(RunOutput(front=[[20.0, 0.0]]), multi, bounds, 0.1) == 0.0    # beyond the reference point
    assert cost(RunOutput(front=[]), multi, bounds) == 0.0


def test_target_runner_command_line(tmp_path):
    setup = make_experiment(tmp_path, mode="single")
    target = tmp_path / "target.json"
    target.write_text(json.dumps({
        "project": str(tmp_path / "project.yaml"), "project_dir": str(tmp_path), "algorithm": "toy",
        "variant": "default", "tuned": ["x", "k"], "base": {"x": 0.1, "k": 1, "op": "b"},
        "budget": {"max_evaluations": 10}, "work_dir": str(tmp_path / "tmp")}))
    env = {**os.environ, ENV_VAR: str(target)}
    cmd = [sys.executable, "-m", "paretolab.tuning.target", "1", "1", "5", "i1"]
    good = subprocess.run([*cmd, "--x=0.7", "--k=3"], capture_output=True, text=True, env=env)
    assert good.returncode == 0, good.stderr
    assert 100 <= float(good.stdout) < 102                # penalty only from the seed noise
    bad = subprocess.run([*cmd, "--op=a"], capture_output=True, text=True, env=env)
    assert bad.returncode == 1 and bad.stdout == "" and "not being tuned" in bad.stderr
    assert not any((tmp_path / "tmp").iterdir())          # each call cleans its folder
    assert setup.exists()


def test_rscript_from_environment(monkeypatch, tmp_path):
    fake = tmp_path / "Rscript.exe"
    fake.write_text("")
    monkeypatch.setenv(r.ENV_VAR, str(fake))
    assert r.find_rscript() == str(fake)


# ---------------------------------------------------------------------------------------------- setup

def test_tuning_bounds_are_checked(tmp_path):
    setup = make_experiment(tmp_path, tuning={"instances": ["i1"], "bounds": {"i2": [[0, 1], [0, 1]],
                                                                               "i1": [[0, 1]]}})
    with pytest.raises(ContractError) as info:
        load_experiment(setup)
    assert "'i2' is not a training instance" in str(info.value) and "one [min, max] per objective" in str(info.value)


def test_tuning_instances_default_to_the_experiment(tmp_path):
    setup = make_experiment(tmp_path, instances=["i2"])
    assert [i.name for i in load_experiment(setup)[2].tuning_instances] == ["i2"]


# ---------------------------------------------------------------------------------------------- pipeline

def test_tuning_then_runs_with_tuned_values(tmp_path, fake_irace):
    setup = make_experiment(tmp_path)
    assert Runner(setup, log=quiet).run() == EXIT_OK
    best = json.loads((unit_folder(tmp_path) / "best.json").read_text())
    assert set(best["parameters"]) == {"x", "k", "op"} and best["source"] == "irace output"
    assert all(p == best["parameters"] for p in run_params(tmp_path))
    bounds = json.loads((tmp_path / "out" / "tuning" / "bounds.json").read_text())
    assert set(bounds) == {"i1", "i2"} and len(bounds["i1"]) == 2
    state = read_state(tmp_path / "out")
    assert state["phase"] == "done" and state["tuning"]["toy/default"]["status"] == "done"
    assert "configurationsFile" in (unit_folder(tmp_path) / "scenario.txt").read_text()

    before = (unit_folder(tmp_path) / "best.json").stat().st_mtime
    assert Runner(setup, log=quiet).run() == EXIT_OK             # tuned units are not tuned again
    assert (unit_folder(tmp_path) / "best.json").stat().st_mtime == before


def test_given_bounds_skip_calibration_and_fixed_parameters_are_not_tuned(tmp_path, fake_irace):
    setup = make_experiment(tmp_path, tuning={"bounds": {"i1": [[0, 3], [-5, 10]], "i2": [[0, 3], [-5, 10]]}},
                            parameters={"toy": {"op": "b"}})
    assert Runner(setup, log=quiet).run() == EXIT_OK
    assert not (tmp_path / "out" / "tuning" / "calibration").exists()
    assert "op" not in (unit_folder(tmp_path) / "parameters.txt").read_text()
    best = json.loads((unit_folder(tmp_path) / "best.json").read_text())
    assert set(best["parameters"]) == {"x", "k"} and best["fixed"]["op"] == "b"
    assert all(p["op"] == "b" and p["x"] == best["parameters"]["x"] for p in run_params(tmp_path))


def test_single_objective_and_nothing_to_tune(tmp_path, fake_irace):
    setup = make_experiment(tmp_path, mode="single")
    assert Runner(setup, log=quiet).run() == EXIT_OK
    assert not (tmp_path / "out" / "tuning" / "bounds.json").exists()
    (tmp_path / "fixed").mkdir()
    fixed = make_experiment(tmp_path / "fixed", mode="single", parameters={"toy": {"x": 0.5, "k": 2, "op": "a"}})
    assert Runner(fixed, log=quiet).run() == EXIT_OK
    assert read_state(fixed.parent / "out")["tuning"]["toy/default"]["status"] == "skipped"


def test_pause_during_tuning_and_resume(tmp_path, fake_irace, monkeypatch):
    monkeypatch.setenv("FAKE_IRACE_SLEEP", "0.3")
    setup = make_experiment(tmp_path, tuning={"bounds": {"i1": [[0, 3], [-5, 10]], "i2": [[0, 3], [-5, 10]]}})
    out = tmp_path / "out"

    def request_pause():
        log = unit_folder(tmp_path) / "irace.Rdata"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if log.is_file() and len(json.loads(log.read_text() or "{}")) >= 3:
                break
            time.sleep(0.05)
        (out / PAUSE_FILE).write_text("")

    threading.Thread(target=request_pause, daemon=True).start()
    assert Runner(setup, log=quiet).run() == EXIT_OK
    state = read_state(out)
    assert state["phase"] == "paused" and "during tuning" in state["message"]
    assert state["tuning"]["toy/default"]["status"] == "paused"
    assert not (unit_folder(tmp_path) / "best.json").exists() and not list(result_files(out / "runs"))

    monkeypatch.setenv("FAKE_IRACE_SLEEP", "0")
    assert Runner(setup, log=quiet).run() == EXIT_OK
    output = (unit_folder(tmp_path) / "irace_output.txt").read_text()
    assert "Recovering from file" in output and output.count("evaluated 1/1") == 1   # nothing evaluated twice
    assert read_state(out)["phase"] == "done" and not (unit_folder(tmp_path) / "irace_recovery.Rdata").exists()


def test_failing_target_stops_with_a_clear_error(tmp_path, fake_irace):
    setup = make_experiment(tmp_path, tuning={"bounds": {"i1": [[0, 3], [-5, 10]], "i2": [[0, 3], [-5, 10]]}})
    project = yaml.safe_load((tmp_path / "project.yaml").read_text())
    project["command"][1] = str(HERE / "missing_solver.py")
    (tmp_path / "project.yaml").write_text(yaml.safe_dump(project))
    assert Runner(setup, log=quiet).run() == EXIT_ERROR
    state = read_state(tmp_path / "out")
    assert state["phase"] == "failed" and "tuning of toy/default failed" in state["message"]
    assert state["tuning"]["toy/default"]["status"] == "failed"


def test_missing_r_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "find_rscript", lambda: None)
    setup = make_experiment(tmp_path)
    assert Runner(setup, log=quiet).run() == EXIT_ERROR
    assert "Rscript not found" in read_state(tmp_path / "out")["message"]


def _irace_available() -> bool:
    found = r.find_rscript()
    return bool(found and r.package_version(found, "irace"))


@pytest.mark.skipif(not os.environ.get("PARETOLAB_TEST_IRACE"), reason="set PARETOLAB_TEST_IRACE=1 (takes ~1 min)")
@pytest.mark.skipif(not _irace_available(), reason="needs R with the irace package")
def test_real_irace(tmp_path):
    setup = make_experiment(tmp_path, tuning={"max_experiments": 300}, parallel_jobs=4)
    assert Runner(setup, log=quiet).run() == EXIT_OK
    best = json.loads((unit_folder(tmp_path) / "best.json").read_text())["parameters"]
    assert best["op"] == "b" and best["k"] == 3 and abs(best["x"] - 0.7) < 0.1
