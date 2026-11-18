import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from paretolab.cli import app
from paretolab.contract import RunResult
from paretolab.contract.layout import result_files
from paretolab.execution import EXIT_DISK, EXIT_OK, Runner
from paretolab.execution.state import PAUSE_FILE, read_state

SOLVER = str(Path(__file__).with_name("fake_solver.py"))


def make_experiment(tmp_path, instances, seeds=2, **setup_extra):
    project = {
        "name": "fake",
        "objectives": [{"name": "f1", "sense": "max"}, {"name": "f2", "sense": "min"}],
        "instances": instances,
        "algorithms": [{"name": "alg", "variants": ["a", "b"],
                        "parameters": [{"name": "k", "type": "integer", "range": [1, 9], "default": 3}]}],
        "command": [sys.executable, SOLVER, "{instance}", "{seed}", "{result_file}", "{params}"],
    }
    setup = {"output_dir": "out", "seeds": {"count": seeds}, "budget": {"max_evaluations": 10}, **setup_extra}
    (tmp_path / "project.yaml").write_text(yaml.safe_dump(project), encoding="utf-8")
    (tmp_path / "experiment.yaml").write_text(yaml.safe_dump(setup), encoding="utf-8")
    return tmp_path / "experiment.yaml"


def results(tmp_path) -> dict:
    out = {}
    for path in result_files(tmp_path / "out" / "runs"):
        r = RunResult.model_validate_json(path.read_text(encoding="utf-8"))
        out[(r.instance, r.variant, r.seed)] = r
    return out


def quiet(*_):
    pass


def test_runs_store_results_and_rerun_skips(tmp_path):
    setup = make_experiment(tmp_path, ["ok"], seeds=3, parameters={"alg/b": {"k": 7}})
    assert Runner(setup, jobs=3, log=quiet).run() == EXIT_OK
    stored = results(tmp_path)
    assert len(stored) == 6 and all(r.status == "ok" for r in stored.values())
    r = stored[("ok", "b", 2)]
    assert r.front == [[2.0, 8.0], [1.0, 10.0]] and r.parameters == {"k": 7}
    assert r.metadata["params"] == ["--k=7"] and r.metadata["paretolab"]["command"][-1] == "--k=7"
    assert stored[("ok", "a", 1)].parameters == {"k": 3}
    folder = tmp_path / "out" / "runs" / "ok" / "alg" / "a" / "seed_1"
    assert sorted(p.name for p in folder.iterdir()) == ["result.json"]
    state = read_state(tmp_path / "out")
    assert state["phase"] == "done" and state["finished"] == 6 and state["failed"] == 0
    before = {p: p.stat().st_mtime_ns for p in result_files(tmp_path / "out" / "runs")}
    runner = Runner(setup, log=quiet)
    assert runner.pending_runs()[0] == []
    runner.run()
    assert before == {p: p.stat().st_mtime_ns for p in result_files(tmp_path / "out" / "runs")}


def test_failures_are_stored_and_retried_on_request(tmp_path):
    setup = make_experiment(tmp_path, ["crash", "bad", "ok"], seeds=1)
    Runner(setup, jobs=2, log=quiet).run()
    stored = results(tmp_path)
    crash, bad = stored[("crash", "a", 1)], stored[("bad", "a", 1)]
    assert crash.status == "error" and "exit code 3" in crash.error_message
    assert "something went wrong" in crash.error_message
    assert bad.status == "error" and "2 objectives" in bad.error_message
    assert stored[("ok", "a", 1)].status == "ok"
    assert (tmp_path / "out" / "runs" / "crash" / "alg" / "a" / "seed_1" / "log.txt").exists()
    assert read_state(tmp_path / "out")["failed"] == 4
    assert len(Runner(setup, log=quiet).pending_runs()[0]) == 0
    assert len(Runner(setup, retry_failed=True, log=quiet).pending_runs()[0]) == 4


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_time_limit_kills_the_whole_tree(tmp_path):
    setup = make_experiment(tmp_path, ["spawner"], seeds=1, algorithms=["alg/a"],
                            budget={"time_limit_s": 1.0, "kill_grace_s": 0.5})
    start = time.monotonic()
    Runner(setup, log=quiet).run()
    assert time.monotonic() - start < 20
    r = results(tmp_path)[("spawner", "a", 1)]
    assert r.status == "error" and "killed" in r.error_message
    pid = int((tmp_path / "out" / "runs" / "spawner" / "alg" / "a" / "seed_1" / "child.pid").read_text())
    assert not _alive(pid)


def test_pause_and_resume(tmp_path):
    setup = make_experiment(tmp_path, ["sleepy"], seeds=4)
    out = tmp_path / "out"

    def request_pause():
        deadline = time.monotonic() + 30
        while not list(result_files(out / "runs")) and time.monotonic() < deadline:
            time.sleep(0.05)
        (out / PAUSE_FILE).write_text("")

    threading.Thread(target=request_pause, daemon=True).start()
    assert Runner(setup, jobs=1, log=quiet).run() == EXIT_OK
    state = read_state(out)
    assert state["phase"] == "paused" and 1 <= state["finished"] < 8
    assert not (out / PAUSE_FILE).exists()
    leftovers = [d for d in (out / "runs").glob("*/*/*/seed_*") if not (d / "result.json").exists()]
    assert leftovers == []                          # the interrupted run was discarded
    assert Runner(setup, jobs=4, log=quiet).run() == EXIT_OK
    assert read_state(out)["phase"] == "done" and len(results(tmp_path)) == 8


def test_low_disk_pauses(tmp_path, monkeypatch):
    setup = make_experiment(tmp_path, ["ok"], seeds=1, min_free_disk_gb=5)
    monkeypatch.setenv("PARETOLAB_TEST_FREE_DISK_GB", "1")
    assert Runner(setup, log=quiet).run() == EXIT_DISK
    assert "GB free" in read_state(tmp_path / "out")["message"]


def test_missing_program_is_an_error_result(tmp_path):
    setup = make_experiment(tmp_path, ["ok"], seeds=1, algorithms=["alg/a"])
    project = yaml.safe_load((tmp_path / "project.yaml").read_text())
    project["command"][0] = str(tmp_path / "does-not-exist")
    (tmp_path / "project.yaml").write_text(yaml.safe_dump(project))
    Runner(setup, log=quiet).run()
    assert "could not start" in results(tmp_path)[("ok", "a", 1)].error_message


def test_invalid_parameter_in_setup(tmp_path):
    make_experiment(tmp_path, ["ok"], parameters={"alg": {"k": 50}, "nope": {}})
    r = CliRunner().invoke(app, ["validate", str(tmp_path / "experiment.yaml")])
    assert r.exit_code == 1 and "outside [1.0, 9.0]" in r.output and "'nope'" in r.output


def test_cli_run_status_pause(tmp_path):
    setup = make_experiment(tmp_path, ["ok"], seeds=2)
    cli = CliRunner()
    assert "not started" in cli.invoke(app, ["status", str(setup)]).output
    r = cli.invoke(app, ["run", str(setup), "-j", "2"])
    assert r.exit_code == 0, r.output
    assert "done: 4 runs, 0 failed" in r.output and "hv: best mean ranks" in r.output
    assert (tmp_path / "out" / "analysis" / "summary.json").exists()
    assert "done: 4 of 4" in cli.invoke(app, ["status", str(setup)]).output
    assert cli.invoke(app, ["pause", str(setup)]).exit_code == 0
    assert (tmp_path / "out" / PAUSE_FILE).exists()
    snapshot = json.loads((tmp_path / "out" / "experiment_used.json").read_text())
    assert snapshot["project"]["name"] == "fake"


@pytest.mark.parametrize("variant", ["a"])
def test_changed_setup_is_reported(tmp_path, variant):
    setup = make_experiment(tmp_path, ["ok"], seeds=1, algorithms=[f"alg/{variant}"])
    Runner(setup, log=quiet).run()
    data = yaml.safe_load(setup.read_text())
    data["budget"]["max_evaluations"] = 20
    setup.write_text(yaml.safe_dump(data))
    messages = []
    Runner(setup, log=messages.append).run()
    assert any("setup changed" in m for m in messages)
