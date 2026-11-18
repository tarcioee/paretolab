"""The web interface's server: API, safety checks, and a whole experiment started, paused and analysed from it."""
import http.client
import json
import subprocess
import sys
import threading
import time

import pytest
import yaml
from test_execution import make_experiment

from paretolab.execution import EXIT_SETUP, Runner
from paretolab.execution.runner import LAUNCHED_AT_ENV
from paretolab.execution.state import PAUSE_FILE, STATE_FILE, read_state, write_json_atomic
from paretolab.web.server import Workspace, finite, make_server


@pytest.fixture
def ui(tmp_path):
    servers = []

    def start(setup_path, project=None):
        server = make_server(Workspace(setup_path, project), port=0)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
        servers.append(server)
        return Client(server)

    yield start
    for server in servers:
        for proc in server.RequestHandlerClass.workspace.children.values():
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        server.shutdown()
        server.server_close()


class Client:
    def __init__(self, server):
        self.port = server.server_address[1]
        self.workspace = server.RequestHandlerClass.workspace

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        sent = {"Host": f"127.0.0.1:{self.port}"}
        if body is not None:
            sent["Content-Type"] = "application/json"
        sent.update(headers or {})
        conn.request(method, path, body=None if body is None else json.dumps(body), headers=sent)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        if response.getheader("Content-Type", "").startswith("application/json"):
            data = json.loads(data)
        return response.status, data

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body=None):
        return self.call("POST", path, {} if body is None else body)

    def wait(self, condition, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            status = self.get("/api/status")[1]
            if condition(status):
                return status
            time.sleep(0.2)
        raise AssertionError(f"timed out; last status: {status['state']} {status['children']}")


def test_pages_project_and_setup(tmp_path, ui):
    c = ui(make_experiment(tmp_path, ["ok"], seeds=2))
    code, page = c.get("/")
    assert code == 200 and b"<title>paretolab</title>" in page
    assert c.get("/static/app.js")[0] == 200
    code, project = c.get("/api/project")
    assert code == 200 and project["manifest"]["name"] == "fake" and project["multiobjective"]
    assert project["indicators"][:2] == ["hv", "igd_plus"]
    code, setup = c.get("/api/setup")
    assert setup["exists"] and setup["data"]["seeds"] == {"count": 2}
    assert setup["check"]["ok"] and setup["check"]["summary"]["runs"] == 4
    assert setup["check"]["summary"]["units"] == ["alg/a", "alg/b"]


def test_requests_from_other_sites_are_refused(tmp_path, ui):
    c = ui(make_experiment(tmp_path, ["ok"]))
    assert c.call("GET", "/api/setup", headers={"Host": "evil.example:80"})[0] == 403      # DNS rebinding
    assert c.call("POST", "/api/pause", {}, headers={"Origin": "http://evil.example"})[0] == 403
    assert c.call("POST", "/api/pause", headers={"Content-Type": "text/plain"})[0] == 415  # plain form post
    assert c.get("/static/../server.py")[0] == 404
    assert c.get("/files/../project.yaml")[0] == 404
    assert c.get("/api/nothing")[0] == 404


def test_check_and_save(tmp_path, ui):
    setup_path = make_experiment(tmp_path, ["ok"])
    original = setup_path.read_text(encoding="utf-8")
    c = ui(setup_path)
    code, check = c.post("/api/check", {"setup": {"output_dir": "out", "seeds": [1], "budget": {}}})
    assert code == 200 and not check["ok"] and check["errors"][0].startswith("budget: budget needs")
    check = c.post("/api/check", {"setup": {"output_dir": "out", "seeds": [1, 1], "budget": {"max_evaluations": 5}}})[1]
    assert check["errors"] == ["(top level): seeds: repeated values [1]"]
    code, check = c.post("/api/check", {"setup": {"output_dir": "out", "seeds": [1], "budget": {"max_evaluations": 5},
                                                  "algorithms": ["alg/zz"]}})
    assert not check["ok"] and "no variant 'zz'" in check["errors"][0]

    code, answer = c.post("/api/save", {"setup": {"output_dir": "out", "seeds": [1]}})
    assert code == 422 and "not saved" in answer["error"]
    assert setup_path.read_text(encoding="utf-8") == original

    new = {"budget": {"max_evaluations": 5}, "seeds": {"count": 3}, "output_dir": "out2",
           "parameters": {"alg/b": {"k": 7}}, "tuning": {"enabled": True, "max_experiments": 50}}
    code, saved = c.post("/api/save", {"setup": new})
    assert code == 200 and saved["check"]["ok"]
    assert saved["check"]["summary"]["tuning"] == [{"unit": "alg/a", "tuned": ["k"]}, {"unit": "alg/b", "tuned": []}]
    text = setup_path.read_text(encoding="utf-8")
    assert text.startswith("# written by the paretolab web interface")
    assert yaml.safe_load(text) == new
    assert list(yaml.safe_load(text)) == ["output_dir", "seeds", "budget", "parameters", "tuning"]   # model order
    assert (tmp_path / "experiment.yaml.bak").read_text(encoding="utf-8") == original


def test_a_new_setup_starts_from_defaults(tmp_path, ui):
    make_experiment(tmp_path, ["ok"])
    c = ui(tmp_path / "new.yaml", tmp_path / "project.yaml")
    setup = c.get("/api/setup")[1]
    assert not setup["exists"] and setup["data"]["project"] == "project.yaml" and setup["check"]["ok"]
    assert c.post("/api/run")[0] == 409          # nothing saved yet
    assert c.get("/api/status")[1]["grid"] is None


def test_run_follow_and_analyse_from_the_interface(tmp_path, ui):
    c = ui(make_experiment(tmp_path, ["ok", "crash"], seeds=2))
    code, started = c.post("/api/run", {})
    assert code == 200 and started["started"] == "run"
    assert c.post("/api/run", {})[0] == 409 or c.workspace.children["run"].poll() is not None
    status = c.wait(lambda s: not s["children"]["run"]["running"])
    assert status["children"]["run"]["exit_code"] == 0
    assert status["state"]["phase"] == "done" and status["state"]["failed"] == 4 and not status["alive"]
    grid = c.get("/api/status")[1]["grid"]
    assert grid["instances"] == ["ok", "crash"] and grid["units"] == ["alg/a", "alg/b"]
    assert grid["cells"][0] == [{"done": 2, "failed": 0, "total": 2}] * 2
    assert grid["cells"][1] == [{"done": 2, "failed": 2, "total": 2}] * 2
    assert "done: 8 runs" in status["logs"]["paretolab.log"] and "analysis written" in status["logs"]["ui_run.log"]

    code, analysis = c.get("/api/analysis")             # `paretolab run` analysed at the end
    assert code == 200 and analysis["available"] and analysis["summary"]["runs_analysed"] == 8
    hv = next(i for i in analysis["indicators"] if i["name"] == "hv")
    assert hv["higher_is_better"] and hv["table"]["units"] == ["alg/a", "alg/b"]
    assert hv["statistics"]["indicator"] == "hv" and set(hv["files"]) >= {"csv", "md", "tex", "statistics"}
    assert any(w.startswith("4 runs ended with status 'error'") for w in analysis["summary"]["warnings"])
    figure = (hv["figures"] + analysis["figures"])[0]
    code, png = c.get(f"{analysis['figure_base']}/{figure}")
    assert code == 200 and png.startswith(b"\x89PNG")
    code, md = c.get(hv["files"]["md"])
    assert code == 200 and b"Hypervolume" in md

    before = analysis["updated_at"]
    assert c.post("/api/analyze", {"no_figures": True})[0] == 200
    status = c.wait(lambda s: not s["children"]["analyze"]["running"])
    assert status["children"]["analyze"]["exit_code"] == 0
    assert c.get("/api/analysis")[1]["updated_at"] >= before


def test_pause_and_resume_from_the_interface(tmp_path, ui):
    c = ui(make_experiment(tmp_path, ["slow"], seeds=2, parallel_jobs=2))
    assert c.post("/api/pause")[0] == 409               # nothing running
    c.post("/api/run", {})
    c.wait(lambda s: s["alive"] and len((s["state"] or {}).get("running", [])) == 2)
    code, answer = c.post("/api/save", {"setup": {"output_dir": "out", "seeds": [1], "budget": {"max_evaluations": 1}}})
    assert code == 409 and "running" in answer["error"]
    assert c.post("/api/pause")[0] == 200
    assert c.get("/api/status")[1]["pause_requested"]
    status = c.wait(lambda s: not s["children"]["run"]["running"], timeout=60)
    assert status["state"]["phase"] == "paused" and status["state"]["finished"] == 0 and not status["alive"]
    assert "paused by request" in status["state"]["message"]
    assert c.post("/api/run", {})[0] == 200             # resume
    c.wait(lambda s: s["alive"])
    c.post("/api/pause")
    c.wait(lambda s: not s["children"]["run"]["running"], timeout=60)


def test_a_second_run_on_the_same_folder_is_refused(tmp_path):
    setup = make_experiment(tmp_path, ["ok"])
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (tmp_path / "out").mkdir()
        write_json_atomic(tmp_path / "out" / STATE_FILE, {"phase": "running", "pid": other.pid})
        lines = []
        assert Runner(setup, log=lines.append).run() == EXIT_SETUP
        assert "another paretolab run" in lines[0]
    finally:
        other.kill()
        other.wait()
    assert Runner(setup, log=lambda *_: None).run() == 0     # the old process is gone: it runs


def test_finite_replaces_nan():
    assert finite({"a": [1.0, float("nan")], "b": float("inf"), "c": "x"}) == {"a": [1.0, None], "b": None, "c": "x"}


def test_a_pause_requested_while_the_run_starts_is_kept(tmp_path, monkeypatch):
    setup = make_experiment(tmp_path, ["ok"])
    pause = tmp_path / "out" / PAUSE_FILE
    pause.parent.mkdir()
    pause.write_text("pause\n")
    monkeypatch.setenv(LAUNCHED_AT_ENV, repr(time.time() - 5))      # launched before the request
    assert Runner(setup, log=lambda *_: None).run() == 0
    assert read_state(tmp_path / "out")["phase"] == "paused" and not pause.exists()
    pause.write_text("pause\n")
    monkeypatch.setenv(LAUNCHED_AT_ENV, repr(time.time() + 5))      # a request left over from before
    assert Runner(setup, log=lambda *_: None).run() == 0
    assert read_state(tmp_path / "out")["phase"] == "done"
