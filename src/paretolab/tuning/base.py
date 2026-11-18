"""The ``Tuner`` interface: what a tuning backend (irace today) must provide."""
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from paretolab.contract.command import format_value
from paretolab.contract.manifest import Parameter, ParamValue


class TunerUnavailable(Exception):
    """The tuner's software is missing; the message says how to install it."""


class TuningFailed(Exception):
    """The tuning of one unit failed; the message says why and where the logs are."""


class TuningPaused(Exception):
    """The tuning stopped on a pause request; the unit resumes on the next ``paretolab run``."""


@dataclass
class TuningUnit:
    """One algorithm variant to tune. Everything a backend needs, already resolved from the setup."""

    algorithm: str
    variant: str
    #: Folder of this unit (``<output_dir>/tuning/<algorithm>/<variant>``); the backend owns it.
    folder: Path
    #: The parameters to search, in manifest order.
    parameters: list[Parameter]
    #: Values of the planned configuration (manifest defaults + setup); a starting point, when complete.
    defaults: dict[str, ParamValue]
    instances: list[str]
    max_experiments: int
    jobs: int
    seed: int
    #: JSON file the generic target runner reads (``python -m paretolab.tuning.target``).
    target_config: Path
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.algorithm}/{self.variant}"


class Tuner(ABC):
    name: str = ""

    @abstractmethod
    def check(self) -> str:
        """The tuner's version text; raises TunerUnavailable with installation hints."""

    @abstractmethod
    def tune(self, unit: TuningUnit, should_stop: Callable[[], bool], log: Callable[[str], None]) -> dict:
        """Run, or resume, the tuning of ``unit``.

        Returns ``{"parameters": {name: value}, "source": text}`` with the best values of ``unit.parameters``
        (a conditional parameter that is inactive in the best configuration is left out). Raises TuningPaused as
        soon as ``should_stop()`` is true (after stopping everything it started) and TuningFailed on errors.
        """


def value_from_text(parameter: Parameter, text: str) -> ParamValue:
    """A tuner's text for ``parameter`` back into a typed, valid value; raises ValueError."""
    text = text.strip().strip("\"'")
    if parameter.type == "integer":
        value = round(float(text))
    elif parameter.type == "real":
        value = float(text)
    else:
        matches = [v for v in parameter.values if format_value(v) == text or str(v) == text]
        if not matches:
            raise ValueError(f"parameter '{parameter.name}': '{text}' is not one of {parameter.values}")
        value = matches[0]
    error = parameter.value_error(value)
    if error:
        raise ValueError(f"parameter '{parameter.name}': {error}")
    return value
