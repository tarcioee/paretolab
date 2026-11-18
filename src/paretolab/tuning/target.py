"""The generic target runner: ONE run of the user's program with a candidate configuration, turned into ONE cost.

The tuner calls it through a small wrapper script that sets ``PARETOLAB_TUNING_TARGET`` (the unit's JSON file):

    target <configuration id> <instance id> <seed> <instance> [<bound>] --name=value ...

* success: prints only the cost (lower is better) and exits with 0;
* failure of any kind: a message on stderr, nothing on stdout, exit code 1 (the tuner stops with that message).

Cost: the best objective value (negated when maximised) for single-objective projects; minus the hypervolume of
the front, normalized with the unit's fixed bounds, for multi-objective projects (an empty front costs 0). A
single-objective run without any feasible solution costs ``EMPTY_COST``.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from paretolab.contract import ContractError, Manifest, RunOutput, load_manifest, load_output, render_command
from paretolab.contract.setup import Budget
from paretolab.execution import process

ENV_VAR = "PARETOLAB_TUNING_TARGET"
EMPTY_COST = 1e300
POLL_S = 0.2


class RunFailed(Exception):
    pass


class Interrupted(Exception):
    pass


def execute(manifest: Manifest, project_dir, *, instance: str, algorithm: str, variant: str, seed: int,
            parameters: dict, budget: Budget, work_dir: Path, should_stop=None) -> RunOutput:
    """Run the user's program once and return its validated output; raises RunFailed or Interrupted."""
    work_dir.mkdir(parents=True, exist_ok=True)
    result_file = work_dir / "output.json"
    args = render_command(manifest, instance=instance, algorithm=algorithm, variant=variant, seed=seed,
                          output_dir=str(work_dir), result_file=str(result_file), parameters=parameters,
                          max_evaluations=budget.max_evaluations, time_limit_s=budget.time_limit_s)
    ceiling = process.kill_ceiling(budget)
    log_path = work_dir / "log.txt"
    with open(log_path, "wb") as log:
        try:
            proc = process.spawn(args, cwd=project_dir, log_file=log)
        except OSError as exc:
            raise RunFailed(f"could not start the program: {exc}; command: {args}") from None
        start = time.monotonic()
        try:
            while proc.poll() is None:
                if should_stop is not None and should_stop():
                    process.kill_tree(proc)
                    raise Interrupted()
                if ceiling is not None and time.monotonic() - start > ceiling:
                    process.kill_tree(proc)
                    raise RunFailed(f"killed: still running {ceiling:.1f} s after start{_tail(log_path)}")
                try:
                    proc.wait(timeout=POLL_S)
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            process.kill_tree(proc)
            raise
    if proc.returncode != 0:
        raise RunFailed(f"exit code {proc.returncode}; command: {args}{_tail(log_path)}")
    try:
        output = load_output(result_file, manifest)
    except ContractError as exc:
        raise RunFailed(f"invalid or missing output: {exc}{_tail(log_path)}") from None
    if output.status == "error":
        raise RunFailed(f"the program reported an error: {output.error_message or '(no message)'}")
    return output


def cost(output: RunOutput, manifest: Manifest, bounds=None, reference_offset: float = 0.1) -> float:
    """Lower is better. ``bounds``: per objective [min, max] (multi-objective only)."""
    if not manifest.is_multiobjective:
        if not output.front:
            return EMPTY_COST
        maximise = manifest.objectives[0].sense == "max"
        values = [p[0] for p in output.front]
        return -max(values) if maximise else min(values)
    if not output.front:
        return 0.0
    import moocore
    import numpy as np

    maximise = np.array([o.sense == "max" for o in manifest.objectives])
    pairs = np.asarray(bounds, dtype=float)
    low = np.where(maximise, -pairs[:, 1], pairs[:, 0])
    span = np.where(pairs[:, 1] > pairs[:, 0], pairs[:, 1] - pairs[:, 0], 1.0)
    front = np.asarray(output.front, dtype=float)
    points = (np.where(maximise, -front, front) - low) / span
    ref = np.full(points.shape[1], 1.0 + reference_offset)
    points = points[(points < ref).all(axis=1)]
    if len(points) == 0:
        return 0.0
    return -float(moocore.hypervolume(points, ref=ref))


def _tail(path: Path, lines: int = 12) -> str:
    try:
        text = path.read_bytes().decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
    return "\n--- last output lines ---\n" + "\n".join(text.splitlines()[-lines:]) if text else ""


# ---------------------------------------------------------------------------------------------- irace calling

def parse_irace_args(argv: list[str]) -> tuple[str, str, int, str, dict]:
    """(configuration id, instance id, seed, instance, {name: text}); a 'bound' between them is ignored."""
    if len(argv) < 4:
        raise RunFailed(f"expected at least 4 arguments (configuration id, instance id, seed, instance), got {argv}")
    config_id, instance_id, seed, instance = argv[:4]
    rest = argv[4:]
    start = next((i for i, t in enumerate(rest) if t.startswith("--")), len(rest))
    values = {}
    for token in rest[start:]:
        if not token.startswith("--") or "=" not in token:
            raise RunFailed(f"unexpected argument '{token}' (expected --name=value)")
        name, value = token[2:].split("=", 1)
        values[name] = value
    try:
        return config_id, instance_id, int(seed), instance, values
    except ValueError:
        raise RunFailed(f"invalid seed '{seed}'") from None


def evaluate(cfg: dict, argv: list[str]) -> float:
    from paretolab.tuning.base import value_from_text

    config_id, instance_id, seed, instance, texts = parse_irace_args(argv)
    manifest = load_manifest(cfg["project"])
    names = {i.name for i in manifest.instances}
    if instance not in names:
        instance = Path(instance).name
    if instance not in names:
        raise RunFailed(f"unknown instance '{instance}'")
    space = {p.name: p for p in manifest.algorithm(cfg["algorithm"]).parameters}
    tuned = set(cfg["tuned"])
    parameters = {k: v for k, v in cfg["base"].items() if k not in tuned}
    for name, text in texts.items():
        if name not in tuned:
            raise RunFailed(f"parameter '{name}' is not being tuned; tuned: {sorted(tuned)}")
        try:
            parameters[name] = value_from_text(space[name], text)
        except ValueError as exc:
            raise RunFailed(str(exc)) from None
    work = Path(cfg["work_dir"]) / f"c{config_id}_i{instance_id}_s{seed}_p{os.getpid()}"
    try:
        output = execute(manifest, cfg["project_dir"], instance=instance, algorithm=cfg["algorithm"],
                         variant=cfg["variant"], seed=seed, parameters=parameters,
                         budget=Budget.model_validate(cfg["budget"]), work_dir=work)
        return cost(output, manifest, (cfg.get("bounds") or {}).get(instance), cfg.get("reference_offset", 0.1))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        path = os.environ.get(ENV_VAR)
        if not path:
            raise RunFailed(f"{ENV_VAR} is not set (the wrapper script written by paretolab sets it)")
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
        value = evaluate(cfg, argv)
    except RunFailed as exc:
        print(f"paretolab target runner: {exc}", file=sys.stderr)
        return 1
    except BaseException as exc:   # never print a made-up cost
        print(f"paretolab target runner: unexpected error: {exc!r}", file=sys.stderr)
        return 1
    print(format(value, ".12g"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
