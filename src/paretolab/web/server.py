"""Local web interface: edit the setup, start, pause and resume the experiment, follow it, read the analysis.

    paretolab ui experiment.yaml [--port 8765] [--no-browser]

The interface is one more front end of the CLI. It writes ``experiment.yaml``, starts ``paretolab run`` and
``paretolab analyze`` as separate processes, and reads ``state.json``, the run results and
``analysis/summary.json``. Closing it does not stop an experiment, and an experiment started from a terminal shows
up in it too. Every form field, label and choice comes from the project manifest.

It listens on 127.0.0.1 only: one user, no authentication. Requests whose Host or Origin is not that address are
refused (DNS rebinding, other web sites), and changes need a JSON body (no plain cross-site form posts).
"""
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml
from pydantic import ValidationError

from paretolab import __version__
from paretolab.contract import ContractError, Manifest, Setup, load_manifest, make_plan
from paretolab.contract.io import describe, read_data
from paretolab.contract.layout import ANALYSIS, RESULT_FILE, RUNS, run_dir
from paretolab.contract.setup import (
    MULTIOBJECTIVE_INDICATORS,
    SINGLE_OBJECTIVE_INDICATORS,
    STATISTICAL_TESTS,
    PlanError,
    tuned_parameter_names,
)
from paretolab.execution import process
from paretolab.execution.runner import LAUNCHED_AT_ENV
from paretolab.execution.state import ACTIVE_PHASES, PAUSE_FILE, read_state

STATIC = Path(__file__).with_name("static")
MAX_BODY = 1 << 20
GRID_REFRESH_S = 3.0
LOG_LINES = 120
#: Screen output of the processes started by the interface, in the output folder.
CHILD_LOG = {"run": "ui_run.log", "analyze": "ui_analyze.log"}
DEFAULT_SETUP = {"output_dir": "results", "seeds": {"count": 10}, "budget": {"max_evaluations": 10000}}


class ApiError(Exception):
    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


def tail(path: Path, lines: int = LOG_LINES, max_bytes: int = 64 * 1024) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def finite(data):
    """``data`` with NaN and infinities replaced by None (JSON has no such numbers)."""
    if isinstance(data, float):
        return data if data == data and abs(data) != float("inf") else None
    if isinstance(data, dict):
        return {k: finite(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [finite(v) for v in data]
    return data


def inside(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def ordered_setup(data: dict) -> dict:
    """The setup's keys in the order of the model (the YAML file reads like the documentation)."""
    order = list(Setup.model_fields)
    return dict(sorted(data.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order)))


def setup_yaml(data: dict) -> str:
    return yaml.safe_dump(ordered_setup(data), sort_keys=False, allow_unicode=True, default_flow_style=None)


class Workspace:
    """Everything the interface knows about one experiment setup file."""

    def __init__(self, setup_path, project_path=None):
        self.setup_path = Path(setup_path).resolve()
        self.base = self.setup_path.parent
        self.default_project = (os.path.relpath(Path(project_path).resolve(), self.base).replace(os.sep, "/")
                                if project_path else "project.yaml")
        self.lock = threading.Lock()
        self.children: dict = {}          # kind -> Popen started by this interface
        self._grid = (0.0, None, None)    # (time, output_dir, grid)
        self._statuses: dict = {}         # result path -> (mtime_ns, status)

    # ------------------------------------------------------------------ files

    def raw_setup(self) -> tuple[dict, str | None, bool]:
        """(setup data, problem reading it, whether the file exists). The data is usable for the form."""
        if not self.setup_path.is_file():
            return {"project": self.default_project, **DEFAULT_SETUP}, None, False
        try:
            data = read_data(self.setup_path)
        except ContractError as exc:
            return {"project": self.default_project, **DEFAULT_SETUP}, str(exc), True
        if not isinstance(data, dict):
            return {"project": self.default_project, **DEFAULT_SETUP}, "expected a mapping at the top level", True
        return data, None, True

    def project_file(self, data: dict) -> Path:
        return (self.base / str(data.get("project") or "project.yaml")).resolve()

    def manifest(self, data: dict) -> Manifest:
        return load_manifest(self.project_file(data))

    def saved_setup(self) -> Setup | None:
        data, problem, exists = self.raw_setup()
        if not exists or problem:
            return None
        try:
            return Setup.model_validate(data)
        except ValidationError:
            return None

    def output_dir(self) -> Path | None:
        data, problem, _ = self.raw_setup()
        if problem or not isinstance(data.get("output_dir"), str):
            return None
        return (self.base / data["output_dir"]).resolve()

    # ------------------------------------------------------------------ API: project and setup

    def project(self) -> dict:
        data, _, _ = self.raw_setup()
        path = self.project_file(data)
        try:
            manifest = self.manifest(data)
        except ContractError as exc:
            raise ApiError(str(exc), HTTPStatus.UNPROCESSABLE_ENTITY) from None
        return {"path": str(path), "manifest": manifest.model_dump(mode="json"),
                "multiobjective": manifest.is_multiobjective,
                "indicators": list(MULTIOBJECTIVE_INDICATORS if manifest.is_multiobjective
                                   else SINGLE_OBJECTIVE_INDICATORS),
                "statistical_tests": list(STATISTICAL_TESTS)}

    def setup(self) -> dict:
        data, problem, exists = self.raw_setup()
        return {"path": str(self.setup_path), "exists": exists, "problem": problem, "data": data,
                "check": self.check(data) if not problem else None, "version": __version__}

    def check(self, data) -> dict:
        """Validation of a setup (as the CLI does it) and what it would run."""
        if not isinstance(data, dict):
            raise ApiError("the setup must be an object")
        out = {"ok": False, "errors": [], "summary": None, "yaml": setup_yaml(data)}
        try:
            setup = Setup.model_validate(data)
        except ValidationError as exc:
            out["errors"] = [line.strip()[2:] for line in describe(exc).splitlines()]
            return out
        try:
            manifest = self.manifest(data)
        except ContractError as exc:
            out["errors"] = [str(exc)]
            return out
        try:
            plan = make_plan(setup, manifest)
        except PlanError as exc:
            out["errors"] = str(exc).splitlines()
            return out
        out["ok"] = True
        out["summary"] = {
            "runs": plan.total_runs, "instances": [i.name for i in plan.instances],
            "units": [f"{a}/{v}" for a, v in plan.units], "seeds": len(plan.seeds), "indicators": plan.indicators,
            "output_dir": str((self.base / setup.output_dir).resolve()),
            "tuning": ([{"unit": f"{a}/{v}", "tuned": tuned_parameter_names(setup, manifest, a, v)}
                        for a, v in plan.units] if setup.tuning.enabled else None),
            "tuning_instances": [i.name for i in plan.tuning_instances]}
        return out

    def save(self, data) -> dict:
        result = self.check(data)
        if not result["ok"]:
            raise ApiError("not saved: the setup has errors\n" + "\n".join(result["errors"]),
                           HTTPStatus.UNPROCESSABLE_ENTITY)
        with self.lock:
            if self.busy():
                raise ApiError("not saved: the experiment is running; pause it first", HTTPStatus.CONFLICT)
            if self.setup_path.is_file():
                backup = self.setup_path.with_name(self.setup_path.name + ".bak")
                backup.write_bytes(self.setup_path.read_bytes())
            header = (f"# written by the paretolab web interface; the previous version is in "
                      f"{self.setup_path.name}.bak\n")
            self.setup_path.write_text(header + result["yaml"], encoding="utf-8")
            self._grid = (0.0, None, None)
        return self.setup()

    # ------------------------------------------------------------------ API: processes

    def _child_alive(self, kind: str) -> bool:
        proc = self.children.get(kind)
        return proc is not None and proc.poll() is None

    def experiment_alive(self, state: dict | None) -> bool:
        if self._child_alive("run"):
            return True
        return bool(state and state.get("phase") in ACTIVE_PHASES and process.pid_alive(state.get("pid")))

    def busy(self) -> bool:
        out = self.output_dir()
        return self.experiment_alive(read_state(out) if out else None) or self._child_alive("analyze")

    def start(self, kind: str, options: dict) -> dict:
        if kind not in CHILD_LOG:
            raise ApiError(f"unknown command '{kind}'")
        with self.lock:
            if self.busy():
                raise ApiError("the experiment (or its analysis) is already running", HTTPStatus.CONFLICT)
            if self.saved_setup() is None:
                raise ApiError("save a valid setup first", HTTPStatus.CONFLICT)
            out = self.output_dir()
            out.mkdir(parents=True, exist_ok=True)
            args = [sys.executable, "-m", "paretolab", kind, str(self.setup_path)]
            if kind == "run" and options.get("retry_failed"):
                args.append("--retry-failed")
            if kind == "analyze" and options.get("no_figures"):
                args.append("--no-figures")
            if kind == "run":
                (out / PAUSE_FILE).unlink(missing_ok=True)
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                       **{LAUNCHED_AT_ENV: repr(time.time())})
            with open(out / CHILD_LOG[kind], "ab") as log:
                log.write(f"\n===== paretolab ui: {' '.join(args[2:])} =====\n".encode())
                log.flush()
                self.children[kind] = subprocess.Popen(args, cwd=str(self.base), stdout=log,
                                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                                       env=env, **process.SPAWN_OPTIONS)
        return {"started": kind, "pid": self.children[kind].pid}

    def pause(self) -> dict:
        out = self.output_dir()
        if out is None or not self.experiment_alive(read_state(out)):
            raise ApiError("the experiment is not running", HTTPStatus.CONFLICT)
        (out / PAUSE_FILE).write_text("pause requested from the web interface\n", encoding="utf-8")
        return {"pause_requested": True}

    def open_folder(self, which: str) -> dict:
        out = self.output_dir()
        folders = {"setup": self.base}
        if out is not None:
            folders |= {"output": out, "analysis": out / ANALYSIS}
        folder = folders.get(which)
        if folder is None or not folder.is_dir():
            raise ApiError(f"no folder '{which}' yet", HTTPStatus.NOT_FOUND)
        if os.name == "nt":
            os.startfile(folder)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"opened": str(folder)}

    # ------------------------------------------------------------------ API: progress

    def status(self) -> dict:
        out = self.output_dir()
        state = read_state(out) if out else None
        children = {}
        for kind, proc in self.children.items():
            children[kind] = {"running": proc.poll() is None, "exit_code": proc.poll(), "pid": proc.pid}
        return {"output_dir": str(out) if out else None, "state": state, "alive": self.experiment_alive(state),
                "pause_requested": bool(out and (out / PAUSE_FILE).exists()), "children": children,
                "grid": self.grid(), "now": time.time(),
                "logs": {"paretolab.log": tail(out / "paretolab.log") if out else "",
                         **{name: tail(out / name) if out else "" for name in CHILD_LOG.values()}}}

    def _status_of(self, path: Path) -> str | None:
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return None
        cached = self._statuses.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            status = json.loads(path.read_text(encoding="utf-8")).get("status", "ok")
        except (OSError, ValueError, AttributeError):
            status = "unreadable"
        self._statuses[path] = (mtime, status)
        return status

    def grid(self) -> dict | None:
        """Finished and failed runs per (instance, algorithm variant) of the saved setup; refreshed every few s."""
        out = self.output_dir()
        stamp, cached_out, cached = self._grid
        if cached is not None and cached_out == out and time.time() - stamp < GRID_REFRESH_S:
            return cached
        setup = self.saved_setup()
        if setup is None or out is None:
            return None
        try:
            plan = make_plan(setup, self.manifest(setup.model_dump()))
        except (ContractError, PlanError):
            return None
        runs = out / RUNS
        cells = []
        for instance in plan.instances:
            row = []
            for algorithm, variant in plan.units:
                done = failed = 0
                for seed in plan.seeds:
                    status = self._status_of(run_dir(runs, instance.name, algorithm, variant, seed) / RESULT_FILE)
                    if status is not None:
                        done += 1
                        failed += status in ("error", "unreadable")
                row.append({"done": done, "failed": failed, "total": len(plan.seeds)})
            cells.append(row)
        grid = {"instances": [i.name for i in plan.instances], "units": [f"{a}/{v}" for a, v in plan.units],
                "cells": cells}
        self._grid = (time.time(), out, grid)
        return grid

    # ------------------------------------------------------------------ API: analysis

    def analysis(self) -> dict:
        out = self.output_dir()
        path = out / ANALYSIS / "summary.json" if out else None
        if path is None or not path.is_file():
            return {"available": False}
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ApiError(f"cannot read {path}: {exc}", HTTPStatus.UNPROCESSABLE_ENTITY) from None
        import pandas as pd

        from paretolab.analysis import tables
        from paretolab.analysis.indicators import LABELS

        analysis_dir = out / ANALYSIS
        figures = [Path(f).name for f in summary.get("figures", [])]
        indicators = []
        for name, info in summary.get("indicators", {}).items():
            entry = {"name": name, "label": LABELS.get(name, name), "higher_is_better": info["higher_is_better"],
                     "files": {}, "table": None, "statistics": None,
                     "figures": [f for f in figures if f == f"cd_{name}.png" or f.startswith((f"box_{name}_",
                                                                                              f"ecdf_{name}_"))]}
            for kind, file in (info.get("tables") or {}).items():
                local = analysis_dir / "tables" / Path(file).name
                if local.is_file():
                    entry["files"][kind] = self.file_url(local)
            csv = analysis_dir / "tables" / f"{name}.csv"
            if csv.is_file():
                units, rows = tables.wide(pd.read_csv(csv), info["higher_is_better"])
                entry["table"] = {"units": units, "rows": [{"instance": str(i), "cells": [
                    {"text": t, "best": bool(b)} for t, b in cells]} for i, cells in rows]}
            stats = analysis_dir / "statistics" / f"{name}.json"
            if stats.is_file():
                entry["statistics"] = json.loads(stats.read_text(encoding="utf-8"))
                entry["files"]["statistics"] = self.file_url(stats)
            indicators.append(entry)
        used = {f for e in indicators for f in e["figures"]}
        per_run = analysis_dir / "indicators_per_run.csv"
        return {"available": True, "summary": {k: v for k, v in summary.items() if k not in ("indicators",
                                                                                               "figures")},
                "updated_at": path.stat().st_mtime, "indicators": indicators,
                "figures": [f for f in figures if f not in used],
                "figure_base": self.file_url(analysis_dir / "figures"),
                "per_run": self.file_url(per_run) if per_run.is_file() else None}

    def file_url(self, path: Path) -> str:
        return "/files/" + path.resolve().relative_to(self.output_dir()).as_posix()

    def file(self, relative: str) -> Path:
        out = self.output_dir()
        if out is None:
            raise ApiError("no output folder", HTTPStatus.NOT_FOUND)
        target = (out / relative).resolve()
        if not inside(out, target) or not target.is_file():
            raise ApiError("not found", HTTPStatus.NOT_FOUND)
        return target


# ---------------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = f"paretolab/{__version__}"
    workspace: Workspace = None   # set by make_server
    allowed_hosts: frozenset = frozenset()

    def log_message(self, format, *args):
        pass

    def _send(self, status, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status=HTTPStatus.OK):
        self._send(status, json.dumps(finite(data), allow_nan=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _error(self, message, status):
        self._json({"error": message}, status)

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.allowed_hosts

    def do_GET(self):
        if not self._host_ok():
            return self._error("forbidden host", HTTPStatus.FORBIDDEN)
        path = urlparse(self.path).path
        w = self.workspace
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path.removeprefix("/static/"))
            if path.startswith("/files/"):
                target = w.file(unquote(path.removeprefix("/files/")))
                kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                if kind.startswith("text/") or target.suffix in (".md", ".tex", ".csv", ".log", ".txt"):
                    kind = "text/plain; charset=utf-8"
                return self._send(HTTPStatus.OK, target.read_bytes(), kind)
            routes = {"/api/project": w.project, "/api/setup": w.setup, "/api/status": w.status,
                      "/api/analysis": w.analysis}
            if path not in routes:
                return self._error("not found", HTTPStatus.NOT_FOUND)
            return self._json(routes[path]())
        except ApiError as exc:
            return self._error(str(exc), exc.status)
        except ValueError as exc:      # e.g. NaN in a summary, or a broken file
            return self._error(f"{type(exc).__name__}: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        origin = self.headers.get("Origin")
        if not self._host_ok() or (origin and urlparse(origin).netloc not in self.allowed_hosts):
            return self._error("forbidden origin", HTTPStatus.FORBIDDEN)
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._error("expected a JSON body", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._error("body too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._error("invalid JSON", HTTPStatus.BAD_REQUEST)
        if not isinstance(body, dict):
            return self._error("expected a JSON object", HTTPStatus.BAD_REQUEST)
        w = self.workspace
        routes = {"/api/check": lambda: w.check(body.get("setup")),
                  "/api/save": lambda: w.save(body.get("setup")),
                  "/api/run": lambda: w.start("run", body),
                  "/api/analyze": lambda: w.start("analyze", body),
                  "/api/pause": w.pause,
                  "/api/open": lambda: w.open_folder(str(body.get("folder")))}
        path = urlparse(self.path).path
        if path not in routes:
            return self._error("not found", HTTPStatus.NOT_FOUND)
        try:
            return self._json(routes[path]())
        except ApiError as exc:
            return self._error(str(exc), exc.status)

    def _static(self, name: str):
        target = (STATIC / name).resolve()
        if not inside(STATIC, target) or not target.is_file():
            return self._error("not found", HTTPStatus.NOT_FOUND)
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind == "application/javascript":
            kind += "; charset=utf-8"
        return self._send(HTTPStatus.OK, target.read_bytes(), kind)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second server listen on a port already in use (requests then go to either
    # one); ask for the port exclusively instead, so a busy port is detected and the next one is tried.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            import socket

            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(workspace: Workspace, port: int = 8765, tries: int = 10) -> ThreadingHTTPServer:
    """A server on 127.0.0.1:port (or the next free port). ``port=0`` picks any free port."""
    last = None
    for candidate in [0] if port == 0 else range(port, port + tries):
        handler = type("BoundHandler", (Handler,), {"workspace": workspace})
        try:
            server = Server(("127.0.0.1", candidate), handler)
        except OSError as exc:
            last = exc
            continue
        real = server.server_address[1]
        handler.allowed_hosts = frozenset({f"127.0.0.1:{real}", f"localhost:{real}"})
        return server
    raise OSError(f"no free port in {port}..{port + tries - 1} ({last})")


def serve(setup_path, project_path=None, port: int = 8765, open_browser: bool = True, log=print) -> None:
    workspace = Workspace(setup_path, project_path)
    server = make_server(workspace, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    log(f"paretolab web interface for {workspace.setup_path}")
    log(f"open {url}  (Ctrl+C stops the interface; a running experiment goes on)")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
