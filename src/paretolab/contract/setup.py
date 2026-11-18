"""Experiment setup (``experiment.yaml``): what to run, and how to analyse it."""
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from paretolab.contract._base import SCHEMA_VERSION, Strict, duplicates
from paretolab.contract.manifest import Instance, Manifest

MULTIOBJECTIVE_INDICATORS = ("hv", "igd_plus", "igd", "epsilon_additive")
SINGLE_OBJECTIVE_INDICATORS = ("best", "gap")
STATISTICAL_TESTS = ("friedman", "nemenyi", "wilcoxon_holm")


class SeedRange(Strict):
    count: int = Field(gt=0)
    start: int = 1


class Budget(Strict):
    max_evaluations: int | None = Field(None, gt=0)
    #: Wall-clock limit of ONE run, in seconds.
    time_limit_s: float | None = Field(None, gt=0)

    @model_validator(mode="after")
    def _check(self):
        if self.max_evaluations is None and self.time_limit_s is None:
            raise ValueError("budget needs 'max_evaluations', 'time_limit_s' or both")
        return self


class Tuning(Strict):
    enabled: bool = False
    tuner: Literal["irace"] = "irace"
    #: Total number of runs the tuner may spend (irace's maxExperiments), per algorithm variant.
    max_experiments: int = Field(1000, gt=0)
    #: Training instances; default: the experiment's instances.
    instances: list[str] | None = None
    #: Budget of each tuning run; default: the experiment's budget.
    budget: Budget | None = None


class Normalization(Strict):
    method: Literal["minmax"] = "minmax"
    #: The hypervolume reference point is placed at 1 + offset in every normalized objective.
    reference_offset: float = Field(0.1, ge=0)


class Statistics(Strict):
    tests: list[Literal["friedman", "nemenyi", "wilcoxon_holm"]] = Field(
        default_factory=lambda: list(STATISTICAL_TESTS))
    alpha: float = Field(0.05, gt=0, lt=1)


class Setup(Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    #: Path of the project manifest, relative to this file.
    project: str = "project.yaml"
    output_dir: str
    #: Instance names; default: all instances of the project.
    instances: list[str] | None = None
    #: ``"algorithm"`` (all its variants) or ``"algorithm/variant"``; default: everything in the project.
    algorithms: list[str] | None = None
    seeds: list[int] | SeedRange
    budget: Budget
    #: Runs at the same time; 0 = number of CPU cores.
    parallel_jobs: int = Field(0, ge=0)
    tuning: Tuning = Field(default_factory=Tuning)
    #: Default: hv + igd_plus (multi-objective); best, plus gap when every instance has a known optimum (single).
    indicators: list[str] | None = None
    normalization: Normalization = Field(default_factory=Normalization)
    statistics: Statistics = Field(default_factory=Statistics)

    @model_validator(mode="after")
    def _check(self):
        if isinstance(self.seeds, list):
            if not self.seeds:
                raise ValueError("seeds: the list is empty")
            if duplicates(self.seeds):
                raise ValueError(f"seeds: repeated values {duplicates(self.seeds)}")
        for label, values in (("instances", self.instances), ("algorithms", self.algorithms),
                              ("indicators", self.indicators)):
            if values is not None and duplicates(values):
                raise ValueError(f"{label}: repeated values {duplicates(values)}")
        return self

    @property
    def seed_list(self) -> list:
        if isinstance(self.seeds, SeedRange):
            return list(range(self.seeds.start, self.seeds.start + self.seeds.count))
        return list(self.seeds)


@dataclass(frozen=True)
class Plan:
    """A setup checked against its manifest: the concrete instances, units and seeds to run."""

    instances: list          # list[Instance]
    units: list              # list[tuple[algorithm, variant]]
    seeds: list
    indicators: list
    tuning_instances: list   # list[Instance]

    @property
    def total_runs(self) -> int:
        return len(self.instances) * len(self.units) * len(self.seeds)


class PlanError(ValueError):
    pass


def make_plan(setup: Setup, manifest: Manifest) -> Plan:
    """Resolve names and defaults of ``setup`` against ``manifest``; raises PlanError listing every problem."""
    problems = []
    known = {i.name for i in manifest.instances}

    def pick_instances(names, label) -> list[Instance]:
        if names is None:
            return list(manifest.instances)
        missing = [n for n in names if n not in known]
        if missing:
            problems.append(f"{label}: unknown instances {missing}; the project has {sorted(known)}")
        return [manifest.instance(n) for n in names if n in known]

    instances = pick_instances(setup.instances, "instances")
    tuning_instances = pick_instances(setup.tuning.instances, "tuning.instances") if setup.tuning.enabled else []

    units = []
    for entry in setup.algorithms or [a.name for a in manifest.algorithms]:
        name, _, variant = entry.partition("/")
        algorithm = next((a for a in manifest.algorithms if a.name == name), None)
        if algorithm is None:
            problems.append(f"algorithms: unknown algorithm '{name}'; the project has "
                            f"{[a.name for a in manifest.algorithms]}")
            continue
        if variant and variant not in algorithm.variants:
            problems.append(f"algorithms: '{name}' has no variant '{variant}'; it has {algorithm.variants}")
            continue
        for v in [variant] if variant else algorithm.variants:
            if (name, v) not in units:
                units.append((name, v))

    if manifest.is_multiobjective:
        allowed, default = MULTIOBJECTIVE_INDICATORS, ["hv", "igd_plus"]
    else:
        allowed = SINGLE_OBJECTIVE_INDICATORS
        default = ["best", "gap"] if instances and all(i.optimum is not None for i in instances) else ["best"]
    indicators = setup.indicators if setup.indicators is not None else default
    wrong = [i for i in indicators if i not in allowed]
    if wrong:
        kind = "multi-objective" if manifest.is_multiobjective else "single-objective"
        problems.append(f"indicators: {wrong} are not available for a {kind} project; choose from {list(allowed)}")
    if "gap" in indicators and not manifest.is_multiobjective:
        no_optimum = [i.name for i in instances if i.optimum is None]
        if no_optimum:
            problems.append(f"indicators: 'gap' needs a known optimum, missing for instances {no_optimum}")

    if problems:
        raise PlanError("\n".join(problems))
    return Plan(instances=instances, units=units, seeds=setup.seed_list, indicators=list(indicators),
                tuning_instances=tuning_instances)
