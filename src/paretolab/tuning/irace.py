"""irace backend: writes the scenario from the manifest's parameter space, runs irace and reads the best
configuration. irace (GPL) runs as a separate R process; paretolab only writes its input files.

Files in the unit folder:

    parameters.txt, instances.txt, scenario.txt, configurations.txt   irace inputs (configurations: the defaults)
    run_irace.R, best.R                                              R scripts (run; read the best from the log)
    target_runner.bat | target_runner.sh                             wrapper for ``python -m paretolab.tuning.target``
    irace.Rdata, irace_output.txt                                    irace's log file and screen output
    irace_recovery.Rdata                                             the log of an interrupted attempt, to resume

Pausing kills irace; the next attempt passes the log it saved (irace saves it after every iteration) as
``recoveryFile``, so only the iteration in progress is lost.
"""
import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from paretolab.contract.command import format_value
from paretolab.execution import process
from paretolab.tuning import rscript as r
from paretolab.tuning.base import Tuner, TunerUnavailable, TuningFailed, TuningPaused, TuningUnit, value_from_text
from paretolab.tuning.target import ENV_VAR

POLL_S = 1.0
LOG, RECOVERY, OUTPUT, BEST_CSV = "irace.Rdata", "irace_recovery.Rdata", "irace_output.txt", "best_irace.csv"
TYPES = {"real": "r", "integer": "i", "categorical": "c", "ordinal": "o"}
SAFE_VALUE = re.compile(r"^[^\s\"'#,()|]+$")

RUN_SCRIPT = """# written by paretolab: runs irace with the scenario of this folder
suppressMessages(library(irace))
args <- c("--scenario", "scenario.txt")
if (exists("irace_cmdline", envir = asNamespace("irace"))) irace::irace_cmdline(args) else irace::irace.cmdline(args)
"""

BEST_SCRIPT = """# written by paretolab; usage: Rscript best.R <irace.Rdata> <out.csv>
args <- commandArgs(trailingOnly = TRUE)
suppressMessages(library(irace))
best <- tryCatch(irace::getFinalElites(irace::read_logfile(args[1]), n = 1L), error = function(e) {
  env <- new.env(); load(args[1], envir = env); r <- env$iraceResults
  r$allConfigurations[r$allConfigurations$.ID. == r$iterationElites[length(r$iterationElites)], , drop = FALSE]
})
write.csv(best, args[2], row.names = FALSE)
"""


def _posix(path) -> str:
    return Path(path).resolve().as_posix()


class IraceTuner(Tuner):
    name = "irace"

    def __init__(self):
        self.rscript = r.find_rscript()

    def check(self) -> str:
        if not self.rscript:
            raise TunerUnavailable(f"Rscript not found. {r.INSTALL_R}")
        version = r.package_version(self.rscript, "irace")
        if not version:
            raise TunerUnavailable(f"R works ({self.rscript}) but the irace package is not installed. "
                                   f"{r.INSTALL_IRACE}")
        return f"irace {version}"

    # ------------------------------------------------------------------ input files

    def parameters_text(self, unit: TuningUnit) -> str:
        lines = [f"# written by paretolab for {unit.key}", "# name  switch  type  domain  | condition"]
        for p in unit.parameters:
            if p.type in ("real", "integer"):
                low, high = p.range
                if p.type == "integer":
                    low, high = int(low), int(high)
                domain = f"({format_value(low)}, {format_value(high)})"
            else:
                bad = [v for v in p.values if not SAFE_VALUE.match(format_value(v))]
                if bad:
                    raise TuningFailed(f"parameter '{p.name}': irace cannot handle the values {bad} "
                                       f"(no spaces, quotes, commas, parentheses, '#' or '|')")
                domain = "(" + ", ".join(f'"{format_value(v)}"' for v in p.values) + ")"
            kind = TYPES[p.type] + (",log" if p.log else "")
            line = f'{p.name} "--{p.name}=" {kind} {domain}'
            lines.append(line + (f" | {p.condition}" if p.condition else ""))
        return "\n".join(lines) + "\n"

    def default_configuration(self, unit: TuningUnit) -> str | None:
        """The planned configuration as irace's first candidate, when it is complete and unconditional."""
        if any(p.condition or p.name not in unit.defaults for p in unit.parameters):
            return None
        names = [p.name for p in unit.parameters]
        return " ".join(names) + "\n" + " ".join(format_value(unit.defaults[n]) for n in names) + "\n"

    def write_inputs(self, unit: TuningUnit, recover: bool) -> None:
        f = unit.folder
        (f / "parameters.txt").write_text(self.parameters_text(unit), encoding="utf-8")
        (f / "instances.txt").write_text("\n".join(unit.instances) + "\n", encoding="utf-8")
        default = self.default_configuration(unit)
        if default:
            (f / "configurations.txt").write_text(default, encoding="utf-8")
        wrapper = self.write_wrapper(unit)
        lines = [f"## written by paretolab for {unit.key}; edit the experiment setup instead",
                 'parameterFile = "parameters.txt"',
                 'trainInstancesDir = ""',
                 'trainInstancesFile = "instances.txt"',
                 f'execDir = "{_posix(f)}"',
                 f'logFile = "{_posix(f / LOG)}"',
                 f'targetRunner = "{_posix(wrapper)}"',
                 f"maxExperiments = {unit.max_experiments}",
                 f"parallel = {unit.jobs}",
                 f"seed = {unit.seed}"]
        if default:
            lines.append('configurationsFile = "configurations.txt"')
        if recover:
            lines.append(f'recoveryFile = "{_posix(f / RECOVERY)}"')
        (f / "scenario.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (f / "run_irace.R").write_text(RUN_SCRIPT, encoding="utf-8")

    def write_wrapper(self, unit: TuningUnit) -> Path:
        target = unit.target_config.resolve()
        if os.name == "nt":
            path = unit.folder / "target_runner.bat"
            text = ("@echo off\r\n"
                    f'set "{ENV_VAR}={target}"\r\n'
                    f'"{sys.executable}" -m paretolab.tuning.target %*\r\n'
                    "exit /b %errorlevel%\r\n")
            path.write_bytes(text.encode("utf-8"))
        else:
            path = unit.folder / "target_runner.sh"
            text = f'#!/bin/sh\n{ENV_VAR}="{target}" exec "{sys.executable}" -m paretolab.tuning.target "$@"\n'
            path.write_text(text, encoding="utf-8")
            path.chmod(0o755)
        return path

    def command(self, unit: TuningUnit) -> list[str]:
        return [self.rscript, "run_irace.R"]

    # ------------------------------------------------------------------ running

    def tune(self, unit: TuningUnit, should_stop, log) -> dict:
        f = unit.folder
        f.mkdir(parents=True, exist_ok=True)
        if (f / LOG).is_file():          # irace writes its log as it goes: the latest state to resume from
            os.replace(f / LOG, f / RECOVERY)
        recover = (f / RECOVERY).is_file()
        code = self._attempt(unit, recover, should_stop, log)
        if code != 0 and recover:
            log(f"{unit.key}: irace could not resume from {RECOVERY} (exit code {code}); starting this unit over")
            (f / RECOVERY).unlink(missing_ok=True)
            code = self._attempt(unit, False, should_stop, log)
        if code != 0:
            raise TuningFailed(f"irace stopped with exit code {code}; last lines of {f / OUTPUT}:\n"
                               + "\n".join(_read(f / OUTPUT).strip().splitlines()[-15:]))
        values, source = self.best(unit)
        (f / RECOVERY).unlink(missing_ok=True)
        return {"parameters": values, "source": source}

    def _attempt(self, unit: TuningUnit, recover: bool, should_stop, log) -> int:
        f = unit.folder
        self.write_inputs(unit, recover)
        shutil.rmtree(f / "tmp", ignore_errors=True)
        log(f"{unit.key}: irace {'resuming' if recover else 'starting'}: {unit.max_experiments} experiments, "
            f"{unit.jobs} in parallel, {len(unit.instances)} training instances")
        env = dict(os.environ)
        for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
            env.setdefault(name, "1")   # irace already runs several target runners at a time
        with open(f / OUTPUT, "ab") as out:
            out.write(f"\n===== paretolab: irace {'resumed' if recover else 'started'} =====\n".encode())
            out.flush()
            proc = subprocess.Popen(self.command(unit), cwd=str(f), stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, env=env, **process.SPAWN_OPTIONS)
            unit.extra.get("guard", process.KillOnExit()).add(proc)
            try:
                while True:
                    try:
                        code = proc.wait(timeout=POLL_S)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    if should_stop():
                        process.kill_tree(proc)
                        shutil.rmtree(f / "tmp", ignore_errors=True)
                        raise TuningPaused(unit.key)
            except BaseException:
                process.kill_tree(proc)
                raise
        shutil.rmtree(f / "tmp", ignore_errors=True)
        return code

    # ------------------------------------------------------------------ result

    def best(self, unit: TuningUnit) -> tuple[dict, str]:
        """Best configuration: from irace's screen output, or else from its log file (through R)."""
        problems = []
        texts = best_from_output(_read(unit.folder / OUTPUT))
        if texts:
            try:
                return self._convert(unit, texts), "irace output"
            except ValueError as exc:
                problems.append(f"output: {exc}")
        else:
            problems.append(f"no '# Best configurations as commandlines' block in {OUTPUT}")
        try:
            return self._convert(unit, self._best_from_log(unit)), "irace log"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            problems.append(f"log: {exc}")
        raise TuningFailed("irace finished but its best configuration could not be read: " + "; ".join(problems))

    def _best_from_log(self, unit: TuningUnit) -> dict:
        f = unit.folder
        if not self.rscript or not (f / LOG).is_file():
            raise RuntimeError(f"no {LOG} or no Rscript")
        (f / "best.R").write_text(BEST_SCRIPT, encoding="utf-8")
        (f / BEST_CSV).unlink(missing_ok=True)
        done = subprocess.run([self.rscript, "best.R", _posix(f / LOG), _posix(f / BEST_CSV)], cwd=str(f),
                              capture_output=True, text=True, timeout=300)
        if done.returncode != 0 or not (f / BEST_CSV).is_file():
            raise RuntimeError(f"best.R failed: {(done.stderr or done.stdout).strip()[-400:]}")
        with open(f / BEST_CSV, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            raise ValueError(f"{BEST_CSV} is empty")
        return {k: v for k, v in rows[0].items() if v not in (None, "", "NA") and not k.startswith(".")}

    @staticmethod
    def _convert(unit: TuningUnit, texts: dict) -> dict:
        space = {p.name: p for p in unit.parameters}
        unknown = sorted(set(texts) - set(space))
        if unknown:
            raise ValueError(f"unknown parameters {unknown}")
        missing = [p.name for p in unit.parameters if p.name not in texts and not p.condition]
        if missing:
            raise ValueError(f"missing parameters {missing}")
        return {p.name: value_from_text(p, texts[p.name]) for p in unit.parameters if p.name in texts}


def best_from_output(text: str) -> dict:
    """``{name: text}`` from the LAST '# Best configurations as commandlines' block of irace's output."""
    lines = text.splitlines()
    found = {}
    for i, line in enumerate(lines):
        if line.startswith("# Best configurations as commandlines"):
            for following in lines[i + 1:]:
                if following.strip() and not following.startswith("#"):
                    found = dict(re.findall(r"--([A-Za-z0-9][A-Za-z0-9_.-]*)=(\S+)", following))
                    break
    return found


def _read(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""
