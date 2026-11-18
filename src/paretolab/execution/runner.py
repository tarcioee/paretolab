"""Runs every planned run of an experiment, in parallel, and stores one result.json per run.

* Resuming is per run: a run whose result.json exists is skipped, so ``paretolab run`` can be repeated at any time.
  Failed runs are stored too (status "error"); ``retry_failed`` runs them again.
* Pausing: create ``<output_dir>/PAUSE`` (``paretolab pause``) or press Ctrl+C. The runs in progress are stopped
  and discarded; the next ``paretolab run`` starts them over.
* Time limit: the program receives ``{time_limit_s}`` and should stop by itself; one still alive after the limit
  plus a grace period is killed (with everything it started) and stored as an error.
* Tuning: with ``tuning.enabled`` the algorithm variants are tuned first (paretolab.tuning.manager); the runs
  then use the tuned values. Pausing works the same way during tuning.
* Disk: before each launch the free space of the output disk is checked; below ``min_free_disk_gb`` the
  experiment pauses with exit code 3.
"""
import os
import shutil
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from paretolab import __version__
from paretolab.contract import ContractError, RunResult, load_experiment, load_output, render_command, write_result
from paretolab.contract.layout import RESULT_FILE, RUNS, run_dir
from paretolab.execution import process
from paretolab.execution.state import (
    ACTIVE_PHASES,
    PAUSE_FILE,
    STATE_FILE,
    format_duration,
    free_disk_gb,
    now_iso,
    read_state,
    write_json_atomic,
)

EXIT_OK, EXIT_ERROR, EXIT_SETUP, EXIT_DISK = 0, 1, 2, 3
#: Set by a launcher (the web interface) to the time it started `paretolab run`; see Runner.run.
LAUNCHED_AT_ENV = "PARETOLAB_LAUNCHED_AT"
OUTPUT_FILE = "output.json"
LOG_FILE = "log.txt"
LOOP_S = 0.2
CONFIG_SNAPSHOT = "experiment_used.json"


@dataclass(frozen=True)
class RunSpec:
    instance: str
    algorithm: str
    variant: str
    seed: int
    parameters: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def id(self) -> str:
        return f"{self.instance}/{self.algorithm}/{self.variant}/seed_{self.seed}"


class Paused(Exception):
    pass


class DiskFull(Exception):
    pass


class Runner:
    def __init__(self, setup_path, jobs: int | None = None, retry_failed: bool = False, log=print,
                 parameters_for=None):
        self.setup, self.manifest, self.plan = load_experiment(setup_path)
        base = Path(setup_path).resolve().parent
        self.output_dir = base / self.setup.output_dir
        self.runs_root = self.output_dir / RUNS
        self.project_file = (base / self.setup.project).resolve()
        self.project_dir = self.project_file.parent
        self.jobs = max(1, jobs or self.setup.parallel_jobs or os.cpu_count() or 1)
        self.retry_failed = retry_failed
        self._print = log
        #: (algorithm, variant) -> the full parameter dict of its runs (default: the planned values)
        self.parameters_for = parameters_for
        self.running: dict = {}
        self.durations: list = []
        self.guard = process.KillOnExit()
        self.state: dict = {}

    # ------------------------------------------------------------------ helpers

    @property
    def pause_file(self) -> Path:
        return self.output_dir / PAUSE_FILE

    def say(self, text: str) -> None:
        self._print(text)
        with open(self.output_dir / "paretolab.log", "a", encoding="utf-8") as f:
            f.write(f"{now_iso()} {text}\n")

    def save_state(self, **fields) -> None:
        self.state.update(fields, updated_at=now_iso(), running=[r["spec"].id for r in self.running.values()])
        if self.durations:
            mean = sum(self.durations) / len(self.durations)
            left = self.state["total"] - self.state["finished"]
            self.state["mean_run_s"] = round(mean, 2)
            self.state["eta_s"] = round(max(left - len(self.running), 0) * mean / self.jobs, 1)
        write_json_atomic(self.output_dir / STATE_FILE, self.state)

    def all_runs(self) -> list[RunSpec]:
        specs = []
        for instance in self.plan.instances:
            for algorithm, variant in self.plan.units:
                params = (self.parameters_for(algorithm, variant) if self.parameters_for
                          else dict(self.plan.parameters[(algorithm, variant)]))
                for seed in self.plan.seeds:
                    specs.append(RunSpec(instance.name, algorithm, variant, seed, params))
        return specs

    def _result_path(self, spec: RunSpec) -> Path:
        return run_dir(self.runs_root, spec.instance, spec.algorithm, spec.variant, spec.seed) / RESULT_FILE

    def pending_runs(self) -> tuple[list, int, int]:
        """(runs to do, runs already finished, failed runs among those)."""
        todo, done, failed = [], 0, 0
        for spec in self.all_runs():
            path = self._result_path(spec)
            if path.is_file():
                try:
                    status = RunResult.model_validate_json(path.read_text(encoding="utf-8")).status
                except ValueError:
                    status = "unreadable"
                if status == "unreadable" or (status == "error" and self.retry_failed):
                    todo.append(spec)
                    continue
                done += 1
                failed += status == "error"
            else:
                todo.append(spec)
        return todo, done, failed

    def _snapshot_config(self) -> None:
        import json

        current = {"setup": self.setup.model_dump(mode="json"), "project": self.manifest.model_dump(mode="json")}
        path = self.output_dir / CONFIG_SNAPSHOT
        if path.is_file():
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                previous = None
            if previous and previous != current:
                changed = [k for k in current if previous.get(k) != current[k]]
                self.say(f"warning: the {' and '.join(changed)} changed since the last run; results already stored "
                         f"were produced with the previous version")
        write_json_atomic(path, current)

    # ------------------------------------------------------------------ main loop

    def run(self) -> int:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        previous = read_state(self.output_dir) or {}
        if (previous.get("phase") in ACTIVE_PHASES and previous.get("pid") not in (None, os.getpid())
                and process.pid_alive(previous["pid"])):
            self._print(f"ERROR: another paretolab run (process {previous['pid']}) is working on {self.output_dir}; "
                        f"pause it or wait for it to finish")
            return EXIT_SETUP
        if self.pause_file.exists():
            # A request made after this run was launched (e.g. from the web interface, while Python was still
            # starting) is kept; an older one is left over from a previous run.
            launched = float(os.environ.get(LAUNCHED_AT_ENV) or 0) or time.time()
            if self.pause_file.stat().st_mtime < launched:
                self.pause_file.unlink()
                self.say("removed an old PAUSE request")
        self._snapshot_config()
        from paretolab.tuning import TuningFailed

        _, done, failed = self.pending_runs()
        total = self.plan.total_runs
        self.state = {"paretolab_version": __version__, "phase": "tuning" if self.setup.tuning.enabled else "running",
                      "pid": os.getpid(), "started_at": now_iso(), "total": total, "finished": done,
                      "failed": failed, "jobs": self.jobs, "message": ""}
        self.save_state()
        try:
            if self.setup.tuning.enabled:
                from paretolab.tuning.manager import TuningStage

                stage = TuningStage(self)
                stage.run()
                self.parameters_for = stage.parameters_for
            queue, done, failed = self.pending_runs()
            self.save_state(phase="running", message="", finished=done, failed=failed)
            limit = self.setup.budget.time_limit_s
            self.say(f"{total} runs planned, {done} already finished, {len(queue)} to run, {self.jobs} at a time"
                     + (f", {format_duration(limit)} per run" if limit else ""))
            self._loop(deque(queue))
        except TuningFailed as exc:
            self.save_state(phase="failed", message=str(exc))
            self.say(f"stopped: {exc}")
            return EXIT_ERROR
        except (Paused, KeyboardInterrupt) as exc:
            self._stop_all()
            how = "Ctrl+C" if isinstance(exc, KeyboardInterrupt) else "request (PAUSE file)"
            where = (" during tuning" if self.state.get("phase") == "tuning"
                     else f": {self.state['finished']} of {total} runs finished")
            self.save_state(phase="paused", message=f"paused by {how}{where}")
            self.say(f"paused{where}; run again to continue")
            return EXIT_OK
        except DiskFull as exc:
            self._stop_all()
            self.save_state(phase="paused", message=str(exc))
            self.say(f"paused: {exc}")
            return EXIT_DISK
        except BaseException:
            self._stop_all()
            self.save_state(phase="failed", message="unexpected error; see paretolab.log")
            raise
        finally:
            if self.pause_file.exists():
                self.pause_file.unlink()
        self.save_state(phase="done", message="all runs finished")
        self.say(f"done: {self.state['finished']} runs, {self.state['failed']} failed")
        return EXIT_OK

    def _loop(self, queue: deque) -> None:
        last_state = 0.0
        while queue or self.running:
            if self.pause_file.exists():
                raise Paused()
            while queue and len(self.running) < self.jobs:
                self._check_disk()
                self._launch(queue.popleft())
            changed = self._kill_overdue()
            for proc, record in list(self.running.items()):
                if proc.poll() is not None:
                    del self.running[proc]
                    self._finish(proc, record)
                    changed = True
            now = time.monotonic()
            if changed or now - last_state > 1.0:
                self.save_state()
                last_state = now
            if self.running:
                try:
                    next(iter(self.running)).wait(timeout=LOOP_S)
                except subprocess.TimeoutExpired:
                    pass

    def _check_disk(self) -> None:
        free = free_disk_gb(self.output_dir)
        if free < self.setup.min_free_disk_gb:
            raise DiskFull(f"only {free:.2f} GB free on the output disk (minimum {self.setup.min_free_disk_gb} GB)")

    # ------------------------------------------------------------------ one run

    def _launch(self, spec: RunSpec) -> None:
        folder = run_dir(self.runs_root, spec.instance, spec.algorithm, spec.variant, spec.seed)
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        budget = self.setup.budget
        args = render_command(self.manifest, instance=spec.instance, algorithm=spec.algorithm,
                              variant=spec.variant, seed=spec.seed, output_dir=str(folder),
                              result_file=str(folder / OUTPUT_FILE), parameters=spec.parameters,
                              max_evaluations=budget.max_evaluations, time_limit_s=budget.time_limit_s)
        log = open(folder / LOG_FILE, "wb")
        record = {"spec": spec, "dir": folder, "args": args, "log": log, "start": time.monotonic()}
        try:
            proc = process.spawn(args, cwd=self.project_dir, log_file=log)
        except OSError as exc:
            log.close()
            self._store_error(record, f"could not start the program: {exc}", elapsed=0.0)
            return
        self.guard.add(proc)
        self.running[proc] = record

    def _kill_overdue(self) -> bool:
        ceiling = process.kill_ceiling(self.setup.budget)
        if ceiling is None:
            return False
        limit = self.setup.budget.time_limit_s
        killed = False
        for proc, record in list(self.running.items()):
            if proc.poll() is None and time.monotonic() - record["start"] > ceiling:
                process.kill_tree(proc)
                del self.running[proc]
                record["log"].close()
                elapsed = time.monotonic() - record["start"]
                self._store_error(record, f"killed: still running {ceiling:.1f} s after start "
                                          f"(time limit {limit} s plus grace)", elapsed=elapsed)
                killed = True
        return killed

    def _finish(self, proc, record) -> None:
        record["log"].close()
        elapsed = time.monotonic() - record["start"]
        if proc.returncode != 0:
            self._store_error(record, f"exit code {proc.returncode}", elapsed)
            return
        spec, folder = record["spec"], record["dir"]
        try:
            output = load_output(folder / OUTPUT_FILE, self.manifest)
        except ContractError as exc:
            self._store_error(record, f"invalid or missing output: {exc}", elapsed)
            return
        result = RunResult.from_output(output, manifest=self.manifest, instance=spec.instance,
                                       algorithm=spec.algorithm, variant=spec.variant, seed=spec.seed,
                                       parameters=spec.parameters)
        if result.wall_time_s is None:
            result.wall_time_s = round(elapsed, 3)
        result.metadata = {**result.metadata, "paretolab": self._provenance(record, elapsed)}
        write_result(folder / RESULT_FILE, result)
        for name in (OUTPUT_FILE, LOG_FILE):
            (folder / name).unlink(missing_ok=True)
        self.durations.append(elapsed)
        self.state["finished"] += 1
        if result.status == "error":
            self.state["failed"] += 1

    def _store_error(self, record, message: str, elapsed: float) -> None:
        spec, folder = record["spec"], record["dir"]
        tail = _tail(folder / LOG_FILE)
        details = f"\n--- last output lines ---\n{tail}" if tail else ""
        result = RunResult(instance=spec.instance, algorithm=spec.algorithm, variant=spec.variant, seed=spec.seed,
                           parameters=spec.parameters, objectives=self.manifest.objectives, front=[],
                           status="error", error_message=message + details,
                           wall_time_s=round(elapsed, 3),
                           metadata={"paretolab": self._provenance(record, elapsed)})
        write_result(folder / RESULT_FILE, result)
        self.durations.append(elapsed)
        self.state["finished"] += 1
        self.state["failed"] += 1
        self.say(f"run {spec.id} failed: {message} (log kept in {folder / LOG_FILE})")

    def _provenance(self, record, elapsed) -> dict:
        return {"version": __version__, "command": record["args"], "measured_wall_time_s": round(elapsed, 3),
                "finished_at": now_iso()}

    def _stop_all(self) -> None:
        """Stop and discard every run in progress (they start over on the next run)."""
        for proc, record in list(self.running.items()):
            process.kill_tree(proc)
            record["log"].close()
            shutil.rmtree(record["dir"], ignore_errors=True)
        self.running.clear()


def _tail(path: Path, lines: int = 15) -> str:
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.strip().splitlines()[-lines:])
