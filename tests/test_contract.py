import json
import math

import pytest
import yaml
from pydantic import ValidationError

from paretolab.contract import (
    ContractError,
    Manifest,
    PlanError,
    RunOutput,
    RunResult,
    Setup,
    load_experiment,
    load_output,
    make_plan,
    render_command,
    write_result,
)

# ---------- manifest ----------

def test_manifest_valid_with_shorthand_and_defaults(biobjective):
    m = Manifest.model_validate(biobjective)
    assert m.is_multiobjective
    assert [i.name for i in m.instances] == ["A", "B"]
    assert m.algorithm("mots").variants == ["default"]


@pytest.mark.parametrize("change, message", [
    (lambda d: d["command"].append("{nope}"), "unknown placeholders"),
    (lambda d: d["command"].remove("{seed}"), "{seed}"),
    (lambda d: d["command"].remove("{result_file}"), "where to write"),
    (lambda d: d["command"].__setitem__(-1, "x{params}"), "token of its own"),
    (lambda d: d.pop("executable"), "'executable' is not set"),
    (lambda d: d["instances"].append("A"), "repeated instances"),
    (lambda d: d["instances"][1].__setitem__("optimum", 3.0), "single-objective"),
    (lambda d: d["algorithms"][0]["parameters"][0].__setitem__("default", 50), "outside"),
    (lambda d: d["algorithms"][0]["parameters"][0].__setitem__("range", [0, 10]), "positive range"),
    (lambda d: d["algorithms"][0]["parameters"][1].__setitem__("default", "flip"), "not one of the values"),
    (lambda d: d["algorithms"][0].__setitem__("variants", ["seq", "seq"]), "repeated variants"),
    (lambda d: d.__setitem__("name", "has space"), "pattern"),
    (lambda d: d.__setitem__("param_format", "--{name}"), "param_format"),
    (lambda d: d.__setitem__("typo_key", 1), "Extra inputs"),
])
def test_manifest_rejects(biobjective, change, message):
    change(biobjective)
    with pytest.raises(ValidationError, match=message.replace("{", r"\{").replace("}", r"\}")):
        Manifest.model_validate(biobjective)


def test_integer_parameter_needs_integer_default(tsp):
    tsp["algorithms"][0]["parameters"] = [{"name": "k", "type": "integer", "range": [1, 5], "default": 2.5}]
    with pytest.raises(ValidationError, match="integer"):
        Manifest.model_validate(tsp)


# ---------- command ----------

def test_render_list_command_expands_params(biobjective):
    m = Manifest.model_validate(biobjective)
    args = render_command(m, instance="B", algorithm="mosa", variant="seq", seed=3, output_dir="out dir",
                          result_file="out dir/r.json", parameters={"t0": 0.5, "op": "swap"})
    assert args == ["./solver", "--inst", "data/B.txt", "--alg", "mosa", "--var", "seq", "--seed", "3",
                    "--out", "out dir/r.json", "--t0=0.5", "--op=swap"]


def test_render_string_command_and_param_format(tsp):
    tsp["command"] = "python ils.py {instance} {seed} {result_file} --budget {max_evaluations} {params}"
    tsp["param_format"] = "--param {name}={value}"
    m = Manifest.model_validate(tsp)
    args = render_command(m, instance="gr17", algorithm="ils", variant="default", seed=1, output_dir="o",
                          result_file="o/r.json", parameters={"k": 2}, max_evaluations=1000)
    assert args == ["python", "ils.py", "gr17", "1", "o/r.json", "--budget", "1000", "--param", "k=2"]


def test_render_missing_value_is_explained(tsp):
    tsp["command"] = "python ils.py {seed} {result_file} {time_limit_s}"
    m = Manifest.model_validate(tsp)
    with pytest.raises(ValueError, match="time_limit_s"):
        render_command(m, instance="gr17", algorithm="ils", variant="default", seed=1, output_dir="o",
                       result_file="o/r.json")


# ---------- setup and plan ----------

def setup_dict(**extra):
    return {"output_dir": "out", "seeds": {"count": 3}, "budget": {"max_evaluations": 100}, **extra}


def test_plan_defaults_multiobjective(biobjective):
    plan = make_plan(Setup.model_validate(setup_dict()), Manifest.model_validate(biobjective))
    assert plan.units == [("mosa", "seq"), ("mosa", "ext"), ("mots", "default")]
    assert plan.seeds == [1, 2, 3]
    assert plan.indicators == ["hv", "igd_plus"]
    assert plan.total_runs == 2 * 3 * 3


def test_plan_selection(biobjective):
    setup = Setup.model_validate(setup_dict(instances=["B"], algorithms=["mosa/ext", "mots"], seeds=[7, 9]))
    plan = make_plan(setup, Manifest.model_validate(biobjective))
    assert [i.name for i in plan.instances] == ["B"]
    assert plan.units == [("mosa", "ext"), ("mots", "default")]
    assert plan.seeds == [7, 9]


def test_plan_single_objective_indicators(tsp):
    m = Manifest.model_validate(tsp)
    assert make_plan(Setup.model_validate(setup_dict()), m).indicators == ["best", "gap"]
    tsp["instances"].append("noopt")
    m = Manifest.model_validate(tsp)
    assert make_plan(Setup.model_validate(setup_dict()), m).indicators == ["best"]
    with pytest.raises(PlanError, match="known optimum"):
        make_plan(Setup.model_validate(setup_dict(indicators=["gap"])), m)


def test_plan_reports_every_problem(biobjective):
    setup = Setup.model_validate(setup_dict(instances=["Z"], algorithms=["nsga", "mosa/zzz"], indicators=["best"]))
    with pytest.raises(PlanError) as err:
        make_plan(setup, Manifest.model_validate(biobjective))
    text = str(err.value)
    for piece in ("unknown instances ['Z']", "unknown algorithm 'nsga'", "no variant 'zzz'", "not available"):
        assert piece in text


@pytest.mark.parametrize("extra, message", [
    ({"budget": {}}, "budget needs"),
    ({"seeds": [1, 1]}, "repeated"),
    ({"seeds": []}, "empty"),
    ({"parallel_jobs": -1}, "greater than or equal"),
])
def test_setup_rejects(extra, message):
    with pytest.raises(ValidationError, match=message):
        Setup.model_validate(setup_dict(**extra))


# ---------- results ----------

def test_output_minimal_and_dimension_check(biobjective):
    out = RunOutput.model_validate({"front": [[10, 2], [8, 1]]})
    assert out.status == "ok" and out.n_objectives == 2
    out.check_against(Manifest.model_validate(biobjective))


@pytest.mark.parametrize("data, message", [
    ({"front": [[1, 2], [3]]}, "different numbers"),
    ({"front": [[1, math.nan]]}, "finite"),
    ({"front": [[1, 2]], "variables": [[0], [1]]}, "variables has 2"),
    ({"front": [[]]}, "no objective values"),
    ({"front": [[1, 2]], "status": "crashed"}, "status"),
])
def test_output_rejects(data, message):
    with pytest.raises(ValidationError, match=message):
        RunOutput.model_validate(data)


def test_result_from_output_and_roundtrip(tmp_path, biobjective):
    m = Manifest.model_validate(biobjective)
    out = RunOutput.model_validate({"front": [[10, 2]], "evaluations": 50,
                                    "convergence_trace": [{"evaluations": 10, "front": [[5, 3]]}]})
    res = RunResult.from_output(out, manifest=m, instance="A", algorithm="mosa", variant="seq", seed=1,
                                parameters={"t0": 1.0})
    path = tmp_path / "r" / "result.json"
    write_result(path, res)
    again = RunResult.model_validate_json(path.read_text(encoding="utf-8"))
    assert again == res
    assert [o.name for o in again.objectives] == ["power", "cost"]


def test_result_dimension_mismatch(tsp):
    out = RunOutput.model_validate({"front": [[1, 2]]})
    with pytest.raises(ValueError, match="1 objectives"):
        RunResult.from_output(out, manifest=Manifest.model_validate(tsp), instance="gr17", algorithm="ils",
                              variant="default", seed=1)


# ---------- files ----------

def test_load_experiment_resolves_project_relative_to_setup(tmp_path, tsp):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "project.yaml").write_text(yaml.safe_dump(tsp), encoding="utf-8")
    (tmp_path / "cfg" / "experiment.yaml").write_text(yaml.safe_dump(setup_dict()), encoding="utf-8")
    _setup, manifest, plan = load_experiment(tmp_path / "cfg" / "experiment.yaml")
    assert manifest.name == "tsp" and plan.total_runs == 2 * 1 * 3


def test_load_errors_are_readable(tmp_path, tsp):
    tsp["objectives"][0]["sense"] = "minimise"
    (tmp_path / "project.yaml").write_text(yaml.safe_dump(tsp), encoding="utf-8")
    (tmp_path / "experiment.yaml").write_text(yaml.safe_dump(setup_dict()), encoding="utf-8")
    with pytest.raises(ContractError, match=r"objectives\.0\.sense"):
        load_experiment(tmp_path / "experiment.yaml")
    (tmp_path / "bad.yaml").write_text("a: [1, 2", encoding="utf-8")
    with pytest.raises(ContractError, match="not valid YAML"):
        load_output(tmp_path / "bad.yaml")
    with pytest.raises(ContractError, match="cannot read"):
        load_output(tmp_path / "missing.json")


def test_load_output_checks_dimension(tmp_path, tsp):
    (tmp_path / "r.json").write_text(json.dumps({"front": [[1, 2]]}), encoding="utf-8")
    with pytest.raises(ContractError, match="1 objectives"):
        load_output(tmp_path / "r.json", Manifest.model_validate(tsp))
