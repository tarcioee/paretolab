"""Turns the manifest's command template into the argument list of one run."""
import shlex
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


def render_command(manifest: Manifest, *, instance: str, algorithm: str, variant: str, seed: int,
                   output_dir: str, result_file: str, parameters: dict | None = None,
                   max_evaluations: int | None = None, time_limit_s: float | None = None) -> list[str]:
    """Argument list (no shell involved) for one run. Values containing spaces stay a single argument."""
    inst = manifest.instance(instance)
    values = _Values({k: v for k, v in {
        "executable": manifest.executable, "instance": inst.name, "instance_path": inst.path or inst.name,
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
