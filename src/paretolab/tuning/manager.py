"""The tuning stage of ``paretolab run``: one tuning per algorithm variant, before the experiment's runs.

* Resuming is per unit: a unit whose ``<output_dir>/tuning/<algorithm>/<variant>/best.json`` exists is done and
  never tuned again (delete the file to redo it). An interrupted unit resumes from the tuner's own log.
* The parameters fixed in the setup are not tuned; a unit with nothing left to tune is skipped.
* Multi-objective cost: the hypervolume needs the same normalization for every run of an instance, so the bounds
  of each training instance are fixed before tuning: given in ``tuning.bounds`` or calibrated from the default
  configurations (``tuning/calibration``, stored in ``tuning/bounds.json``).
"""
import json
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from paretolab import __version__
from paretolab.contract import RunOutput
from paretolab.contract.setup import tuned_parameter_names
from paretolab.execution.state import now_iso, write_json_atomic
from paretolab.tuning.base import TunerUnavailable, TuningFailed, TuningPaused, TuningUnit
from paretolab.tuning.irace import IraceTuner
from paretolab.tuning.target import Interrupted, RunFailed, execute

TUNING = "tuning"
BEST_FILE = "best.json"
TARGET_FILE = "target.json"
BOUNDS_FILE = "bounds.json"
TUNERS = {"irace": IraceTuner}


class TuningStage:
    def __init__(self, runner):
        self.runner = runner
        self.setup, self.manifest, self.plan = runner.setup, runner.manifest, runner.plan
        self.root = runner.output_dir / TUNING
        self.budget = self.setup.tuning.budget or self.setup.budget
        self.units = {f"{a}/{v}": {"status": "pending"} for a, v in self.plan.units}

    # ------------------------------------------------------------------ results

    def folder(self, algorithm: str, variant: str) -> Path:
        return self.root / algorithm / variant

    def load_best(self, algorithm: str, variant: str) -> dict | None:
        path = self.folder(algorithm, variant) / BEST_FILE
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def tuned_names(self, algorithm: str, variant: str) -> list[str]:
        return tuned_parameter_names(self.setup, self.manifest, algorithm, variant)

    def parameters_for(self, algorithm: str, variant: str) -> dict:
        """The full parameter set of a unit's runs: the planned values with the tuned ones on top."""
        base = dict(self.plan.parameters[(algorithm, variant)])
        best = self.load_best(algorithm, variant)
        if best is None:
            return base
        tuned = set(self.tuned_names(algorithm, variant))
        values = {k: v for k, v in base.items() if k not in tuned}
        values.update({k: v for k, v in best["parameters"].items() if k in tuned})
        return values

    # ------------------------------------------------------------------ main

    def _update(self, key: str, **fields) -> None:
        self.units[key].update(fields)
        self.runner.state["tuning"] = self.units
        self.runner.save_state(phase="tuning", message=fields.get("message", ""))

    def should_stop(self) -> bool:
        return self.runner.pause_file.exists()

    def run(self) -> None:
        """Tune every unit not tuned yet. Raises the runner's Paused, TuningFailed or KeyboardInterrupt."""
        from paretolab.execution.runner import Paused

        todo = []
        for algorithm, variant in self.plan.units:
            key = f"{algorithm}/{variant}"
            if not self.tuned_names(algorithm, variant):
                self.units[key] = {"status": "skipped", "message": "every parameter is fixed in the setup"}
            elif self.load_best(algorithm, variant) is not None:
                self.units[key] = {"status": "done", "message": f"tuned before ({BEST_FILE})"}
            else:
                todo.append((algorithm, variant))
        self.runner.state["tuning"] = self.units
        if not todo:
            return
        tuner = TUNERS[self.setup.tuning.tuner]()
        try:
            version = tuner.check()
        except TunerUnavailable as exc:
            raise TuningFailed(f"tuning is enabled but {exc} Or set tuning.enabled: false.") from None
        self.runner.say(f"tuning {len(todo)} algorithm variants with {version} on "
                        f"{len(self.plan.tuning_instances)} training instances")
        try:
            bounds = self.bounds() if self.manifest.is_multiobjective else {}
        except Interrupted:
            raise Paused() from None
        for algorithm, variant in todo:
            key = f"{algorithm}/{variant}"
            unit = self._unit(algorithm, variant, bounds)
            self._update(key, status="running", started_at=now_iso(), message=f"tuning {key}")
            start = time.monotonic()
            try:
                result = tuner.tune(unit, self.should_stop, self.runner.say)
            except TuningPaused:
                self._update(key, status="paused", message=f"tuning of {key} paused; it resumes on the next run")
                raise Paused() from None
            except KeyboardInterrupt:
                self._update(key, status="paused", message=f"tuning of {key} stopped by Ctrl+C")
                raise
            except TuningFailed as exc:
                self._update(key, status="failed", message=str(exc))
                raise TuningFailed(f"tuning of {key} failed: {exc}\n(files in {unit.folder}; run again to "
                                   f"retry, or fix the values in the setup's 'parameters')") from None
            elapsed = round(time.monotonic() - start, 1)
            write_json_atomic(unit.folder / BEST_FILE, {
                "algorithm": algorithm, "variant": variant, "parameters": result["parameters"],
                "fixed": {k: v for k, v in self.plan.parameters[(algorithm, variant)].items()
                          if k not in self.tuned_names(algorithm, variant)},
                "tuner": version, "source": result["source"], "instances": unit.instances,
                "max_experiments": unit.max_experiments, "seed": unit.seed,
                "budget": self.budget.model_dump(exclude_none=True), "elapsed_s": elapsed,
                "paretolab_version": __version__, "finished_at": now_iso()})
            self._update(key, status="done", elapsed_s=elapsed, parameters=result["parameters"],
                         message=f"{key} tuned: {result['parameters']}")
            self.runner.say(f"{key}: tuned in {elapsed:.0f} s: {result['parameters']}")

    def _unit(self, algorithm: str, variant: str, bounds: dict) -> TuningUnit:
        folder = self.folder(algorithm, variant)
        folder.mkdir(parents=True, exist_ok=True)
        names = self.tuned_names(algorithm, variant)
        target = folder / TARGET_FILE
        write_json_atomic(target, {
            "project": str(self.runner.project_file),
            "project_dir": str(self.runner.project_dir.resolve()),
            "algorithm": algorithm, "variant": variant, "tuned": names,
            "base": self.plan.parameters[(algorithm, variant)],
            "budget": self.budget.model_dump(exclude_none=True),
            "work_dir": str((folder / "tmp").resolve()),
            "bounds": bounds, "reference_offset": self.setup.normalization.reference_offset})
        space = {p.name: p for p in self.manifest.algorithm(algorithm).parameters}
        return TuningUnit(algorithm=algorithm, variant=variant, folder=folder,
                          parameters=[space[n] for n in names], defaults=self.plan.parameters[(algorithm, variant)],
                          instances=[i.name for i in self.plan.tuning_instances],
                          max_experiments=self.setup.tuning.max_experiments, jobs=self.runner.jobs,
                          seed=self.setup.tuning.seed, target_config=target, extra={"guard": self.runner.guard})

    # ------------------------------------------------------------------ bounds (multi-objective)

    def bounds(self) -> dict:
        given = self.setup.tuning.bounds
        path = self.root / BOUNDS_FILE
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        missing = [i.name for i in self.plan.tuning_instances if i.name not in given and i.name not in stored]
        if missing:
            stored.update(self.calibrate(missing))
            self.root.mkdir(parents=True, exist_ok=True)
            write_json_atomic(path, stored)
        return {**stored, **{k: [list(p) for p in v] for k, v in given.items()}}

    def calibrate(self, instances: list[str]) -> dict:
        """Run each unit's planned configuration on ``instances`` and take the bounds of all fronts."""
        n = self.setup.tuning.calibration_runs
        folder = self.root / "calibration"
        specs = [(i, a, v, s) for i in instances for a, v in self.plan.units for s in range(1, n + 1)]

        def path(spec):
            i, a, v, s = spec
            return folder / i / a / v / f"seed_{s}.json"

        todo = [s for s in specs if not path(s).is_file()]
        self.runner.say(f"calibrating the hypervolume bounds of {len(instances)} training instances: "
                        f"{len(specs)} runs of the default configurations ({len(specs) - len(todo)} already done)")
        abort = threading.Event()

        def stop() -> bool:
            return abort.is_set() or self.should_stop()

        def one(spec):
            i, a, v, s = spec
            work = path(spec).with_suffix("")
            shutil.rmtree(work, ignore_errors=True)
            output = execute(self.manifest, self.runner.project_dir, instance=i, algorithm=a, variant=v, seed=s,
                             parameters=self.plan.parameters[(a, v)], budget=self.budget, work_dir=work,
                             should_stop=stop)
            write_json_atomic(path(spec), {"front": output.front, "status": output.status})
            shutil.rmtree(work, ignore_errors=True)

        done = len(specs) - len(todo)
        with ThreadPoolExecutor(max_workers=self.runner.jobs) as pool:
            pending = {pool.submit(one, s): s for s in todo}
            try:
                while pending:
                    finished, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                    for future in finished:
                        spec = pending.pop(future)
                        try:
                            future.result()
                        except RunFailed as exc:
                            raise TuningFailed(f"calibration run {'/'.join(map(str, spec))} failed: {exc}\n"
                                               f"(or give tuning.bounds for this instance)") from None
                        done += 1
                    if finished:
                        self.runner.save_state(phase="tuning", message=f"calibrating bounds: {done} of "
                                                                       f"{len(specs)} runs")
            except BaseException:
                abort.set()
                raise
        result = {}
        for instance in instances:
            points = [p for s in specs if s[0] == instance
                      for p in RunOutput.model_validate_json(path(s).read_text(encoding="utf-8")).front]
            if not points:
                raise TuningFailed(f"no calibration run found a solution on instance '{instance}'; "
                                   f"give its bounds in tuning.bounds")
            result[instance] = [[min(col), max(col)] for col in zip(*points, strict=True)]
        return result
