"""Turns the manifest's command template into the argument list of one run."""
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from paretolab.contract.manifest import Manifest, command_tokens


class _Values(dict):
    def __missing__(self, key):
        raise ValueError(f"the command uses '{{{key}}}' but this run has no value for it "
                         f"(set it in the setup, e.g. budget.max_evaluations or budget.time_limit_s)")


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def resolve_executable(executable: str | None, project_dir=None) -> str | None:
    """A path-like ``executable`` ("./solver", "bin/solver") made absolute against the project folder, so it does
    not depend on the current directory; on Windows ".exe" is added when only that file exists. A bare name
    ("solver") is left for the system to find on the PATH."""
    if not executable or project_dir is None:
        return executable
    if not (executable.startswith(".") or "/" in executable or "\\" in executable):
        return executable
    path = Path(project_dir) / executable
    if os.name == "nt" and not path.is_file() and path.with_name(path.name + ".exe").is_file():
        path = path.with_name(path.name + ".exe")
    return str(path.resolve())


def render_command(manifest: Manifest, *, instance: str, algorithm: str, variant: str, seed: int,
                   output_dir: str, result_file: str, parameters: dict | None = None,
                   max_evaluations: int | None = None, time_limit_s: float | None = None,
                   project_dir=None) -> list[str]:
    """Argument list (no shell involved) for one run. Values containing spaces stay a single argument.

    ``{python}`` is the interpreter running paretolab; ``{executable}`` is resolved against ``project_dir``.
    """
    inst = manifest.instance(instance)
    values = _Values({k: v for k, v in {
        "python": sys.executable, "executable": resolve_executable(manifest.executable, project_dir),
        "instance": inst.name, "instance_path": inst.path or inst.name,
        "algorithm": algorithm, "variant": variant, "seed": seed, "output_dir": output_dir,
        "result_file": result_file, "max_evaluations": max_evaluations, "time_limit_s": time_limit_s,
    }.items() if v is not None})
    values = _Values({k: format_value(v) for k, v in values.items()})
    param_tokens = shlex.split(manifest.param_format)
    args = []
    for token in command_tokens(manifest.command):
        if token == "{params}":
            for name, value in (parameters or {}).items():
                args += [t.format(name=name, value=format_value(value)) for t in param_tokens]
        else:
            args.append(token.format_map(values))
    return args
