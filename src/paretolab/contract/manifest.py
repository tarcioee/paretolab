"""Project manifest (``project.yaml``): what the problem is and how to run one algorithm execution."""
import shlex
import string
from typing import Literal

from pydantic import Field, field_validator, model_validator

from paretolab.contract._base import SCHEMA_VERSION, Name, Sense, Strict, duplicates

#: Placeholders accepted in ``command``. ``{params}`` must be a token of its own: it expands to several arguments.
PLACEHOLDERS = frozenset({"executable", "instance", "instance_path", "algorithm", "variant", "seed",
                          "max_evaluations", "time_limit_s", "output_dir", "result_file", "params"})
ParamValue = bool | int | float | str


def placeholders_of(text: str) -> set:
    """Names of the ``{placeholders}`` used in ``text`` (escaped ``{{`` braces are ignored)."""
    return {field for _, field, _, _ in string.Formatter().parse(text) if field is not None}


def command_tokens(command: str | list) -> list:
    """The command template as a list of tokens (a string template is split like a POSIX shell would)."""
    return list(command) if isinstance(command, list) else shlex.split(command)


class Objective(Strict):
    name: Name
    sense: Sense
    unit: str | None = None


class Instance(Strict):
    name: Name
    path: str | None = None
    #: Known optimal objective value (single-objective projects only); enables the ``gap`` indicator.
    optimum: float | None = None


class Parameter(Strict):
    """One tunable hyperparameter (the types follow irace: real, integer, categorical, ordinal)."""

    name: Name
    type: Literal["real", "integer", "categorical", "ordinal"]
    range: tuple[float, float] | None = None
    values: list[ParamValue] | None = None
    default: ParamValue | None = None
    log: bool = False
    #: Condition passed to the tuner as is (irace syntax), e.g. ``"op == 'swap'"``.
    condition: str | None = None

    @model_validator(mode="after")
    def _check(self):
        numeric = self.type in ("real", "integer")
        if numeric:
            if self.range is None:
                raise ValueError(f"parameter '{self.name}': type '{self.type}' needs 'range: [low, high]'")
            if self.values is not None:
                raise ValueError(f"parameter '{self.name}': 'values' is only for categorical/ordinal parameters")
            low, high = self.range
            if not low < high:
                raise ValueError(f"parameter '{self.name}': range low must be smaller than high")
            if self.type == "integer" and (low != int(low) or high != int(high)):
                raise ValueError(f"parameter '{self.name}': an integer range needs integer bounds")
            if self.log and low <= 0:
                raise ValueError(f"parameter '{self.name}': log scale needs a positive range")
            if self.default is not None:
                if isinstance(self.default, (str, bool)) or not low <= self.default <= high:
                    raise ValueError(f"parameter '{self.name}': default {self.default!r} is outside {list(self.range)}")
                if self.type == "integer" and self.default != int(self.default):
                    raise ValueError(f"parameter '{self.name}': default must be an integer")
        else:
            if not self.values:
                raise ValueError(f"parameter '{self.name}': type '{self.type}' needs a non-empty 'values' list")
            if self.range is not None or self.log:
                raise ValueError(f"parameter '{self.name}': 'range' and 'log' are only for real/integer parameters")
            if duplicates(str(v) for v in self.values):
                raise ValueError(f"parameter '{self.name}': repeated values {duplicates(str(v) for v in self.values)}")
            if self.default is not None and self.default not in self.values:
                raise ValueError(f"parameter '{self.name}': default {self.default!r} is not one of the values")
        return self


class Algorithm(Strict):
    name: Name
    #: Variants share the algorithm's parameter space (e.g. strategies); each one is tuned and compared on its own.
    variants: list[Name] = Field(default_factory=lambda: ["default"], min_length=1)
    parameters: list[Parameter] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self):
        if duplicates(self.variants):
            raise ValueError(f"algorithm '{self.name}': repeated variants {duplicates(self.variants)}")
        repeated = duplicates(p.name for p in self.parameters)
        if repeated:
            raise ValueError(f"algorithm '{self.name}': repeated parameters {repeated}")
        return self


class Manifest(Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    name: Name
    description: str = ""
    objectives: list[Objective] = Field(min_length=1)
    instances: list[Instance] = Field(min_length=1)
    algorithms: list[Algorithm] = Field(min_length=1)
    #: Program to run; referenced in ``command`` as ``{executable}``.
    executable: str | None = None
    #: Command line of ONE run, as a list of tokens (recommended) or a string split like a POSIX shell.
    command: list[str] | str
    #: How each hyperparameter is passed; split into tokens the same way, e.g. ``"--param {name}={value}"``.
    param_format: str = "--{name}={value}"

    @field_validator("instances", mode="before")
    @classmethod
    def _instance_shorthand(cls, value):
        # "- burma14" is accepted as a shorthand for "- {name: burma14}"
        if isinstance(value, list):
            return [{"name": v} if isinstance(v, str) else v for v in value]
        return value

    @model_validator(mode="after")
    def _check(self):
        for label, names in (("objectives", [o.name for o in self.objectives]),
                             ("instances", [i.name for i in self.instances]),
                             ("algorithms", [a.name for a in self.algorithms])):
            if duplicates(names):
                raise ValueError(f"repeated {label}: {duplicates(names)}")
        if self.is_multiobjective and any(i.optimum is not None for i in self.instances):
            raise ValueError("'optimum' is only for single-objective projects (one objective)")
        self._check_command()
        return self

    def _check_command(self):
        try:
            tokens = command_tokens(self.command)
        except ValueError as exc:
            raise ValueError(f"command: cannot split the string ({exc}); write it as a list of tokens") from None
        if not tokens:
            raise ValueError("command is empty")
        used = set()
        for token in tokens:
            fields = placeholders_of(token)
            unknown = fields - PLACEHOLDERS
            if unknown:
                raise ValueError(f"command: unknown placeholders {sorted(unknown)}; allowed: {sorted(PLACEHOLDERS)}")
            if "params" in fields and token != "{params}":
                raise ValueError("command: '{params}' must be a token of its own")
            used |= fields
        if "seed" not in used:
            raise ValueError("command must pass '{seed}' to the program (runs have to be reproducible)")
        if not used & {"result_file", "output_dir"}:
            raise ValueError("command must pass '{result_file}' or '{output_dir}' so the program knows where to write")
        if "executable" in used and not self.executable:
            raise ValueError("command uses '{executable}' but 'executable' is not set")
        if placeholders_of(self.param_format) != {"name", "value"}:
            raise ValueError("param_format must use exactly '{name}' and '{value}'")

    @property
    def is_multiobjective(self) -> bool:
        return len(self.objectives) > 1

    def instance(self, name: str) -> Instance:
        return next(i for i in self.instances if i.name == name)

    def algorithm(self, name: str) -> Algorithm:
        return next(a for a in self.algorithms if a.name == name)
