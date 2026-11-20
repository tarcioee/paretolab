"""Experiment setup (``experiment.yaml``): what to run, and how to analyse it."""
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from paretolab.contract._base import SCHEMA_VERSION, Strict, duplicates
from paretolab.contract.manifest import Instance, Manifest, ParamValue
from paretolab.messages import note, under

MULTIOBJECTIVE_INDICATORS = ("hv", "igd_plus", "igd", "epsilon_additive")
SINGLE_OBJECTIVE_INDICATORS = ("best", "gap")
STATISTICAL_TESTS = ("friedman", "nemenyi", "wilcoxon_holm")


class SeedRange(Strict):
    count: int = Field(gt=0)
    start: int = 1


class Budget(Strict):
    max_evaluations: int | None = Field(None, gt=0)
    #: Wall-clock limit of ONE run, in seconds. The program receives it ({time_limit_s}) and should stop by itself.
    time_limit_s: float | None = Field(None, gt=0)
    #: A run still alive after time_limit_s + this grace is killed (default: max(10 s, 10% of the limit)).
    kill_grace_s: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _check(self):
        if self.max_evaluations is None and self.time_limit_s is None:
            raise ValueError(note("budget_empty", "budget needs 'max_evaluations', 'time_limit_s' or both"))
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
    #: Seed of the tuner itself (irace's ``seed``), so a tuning can be repeated.
    seed: int = 1
    #: Multi-objective only. The tuning cost is the hypervolume of each run's front after a min-max normalization
    #: with FIXED bounds per training instance: ``{instance: [[min, max], ...]}``, one pair per objective. Instances
    #: left out are calibrated: every algorithm variant runs its default configuration ``calibration_runs`` times
    #: and the bounds are taken from the union of the fronts.
    bounds: dict[str, list[tuple[float, float]]] = Field(default_factory=dict)
    calibration_runs: int = Field(3, gt=0)


class Normalization(Strict):
    method: Literal["minmax"] = "minmax"
    #: The hypervolume reference point is placed at 1 + offset in every normalized objective.
    reference_offset: float = Field(0.1, ge=0)


class Statistics(Strict):
    tests: list[Literal["friedman", "nemenyi", "wilcoxon_holm"]] = Field(
        default_factory=lambda: list(STATISTICAL_TESTS))
    alpha: float = Field(0.05, gt=0, lt=1)
    #: What a block (a "row" of the tests) is: one instance (its runs aggregated), or one (instance, seed) pair.
    #: With a single instance, "instances" falls back to "runs".
    blocks: Literal["instances", "runs"] = "instances"
    aggregation: Literal["median", "mean"] = "median"


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
    #: Fixed hyperparameter values, keyed by "algorithm" or "algorithm/variant" (the latter wins); they override
    #: the manifest defaults. With tuning enabled, the parameters fixed here are not tuned; the others are.
    parameters: dict[str, dict[str, ParamValue]] = Field(default_factory=dict)
    #: Runs are paused (exit code 3) when the output disk has less free space than this.
    min_free_disk_gb: float = Field(1.0, ge=0)
    tuning: Tuning = Field(default_factory=Tuning)
    #: Default: hv + igd_plus (multi-objective); best, plus gap when every instance has a known optimum (single).
    indicators: list[str] | None = None
    normalization: Normalization = Field(default_factory=Normalization)
    statistics: Statistics = Field(default_factory=Statistics)

    @model_validator(mode="after")
    def _check(self):
        if isinstance(self.seeds, list):
            if not self.seeds:
                raise ValueError(note("seeds_empty", "seeds: the list is empty"))
            if duplicates(self.seeds):
                raise ValueError(note("repeated_values", "{field}: repeated values {values}", field="seeds",
                                      values=duplicates(self.seeds)))
        for label, values in (("instances", self.instances), ("algorithms", self.algorithms),
                              ("indicators", self.indicators)):
            if values is not None and duplicates(values):
                raise ValueError(note("repeated_values", "{field}: repeated values {values}", field=label,
                                      values=duplicates(values)))
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
    parameters: dict         # {(algorithm, variant): {name: value}}: manifest defaults + setup values

    @property
    def total_runs(self) -> int:
        return len(self.instances) * len(self.units) * len(self.seeds)


class PlanError(ValueError):
    """Every problem found when resolving a setup against a manifest; ``problems`` keeps them one by one."""

    def __init__(self, problems: list):
        super().__init__("\n".join(problems))
        self.problems = list(problems)


def make_plan(setup: Setup, manifest: Manifest) -> Plan:
    """Resolve names and defaults of ``setup`` against ``manifest``; raises PlanError listing every problem."""
    problems = []
    known = {i.name for i in manifest.instances}

    def pick_instances(names, label) -> list[Instance]:
        if names is None:
            return list(manifest.instances)
        missing = [n for n in names if n not in known]
        if missing:
            problems.append(note("unknown_instances", "{field}: unknown instances {missing}; the project has {known}",
                                 field=label, missing=missing, known=sorted(known)))
        return [manifest.instance(n) for n in names if n in known]

    instances = pick_instances(setup.instances, "instances")
    tuning_instances = []
    if setup.tuning.enabled:
        tuning_instances = (pick_instances(setup.tuning.instances, "tuning.instances")
                            if setup.tuning.instances is not None else list(instances))
        _check_bounds(setup, manifest, tuning_instances, problems)

    units = []
    for entry in setup.algorithms or [a.name for a in manifest.algorithms]:
        name, _, variant = entry.partition("/")
        algorithm = next((a for a in manifest.algorithms if a.name == name), None)
        if algorithm is None:
            problems.append(note("unknown_algorithm", "algorithms: unknown algorithm '{name}'; the project has {known}",
                                 name=name, known=[a.name for a in manifest.algorithms]))
            continue
        if variant and variant not in algorithm.variants:
            problems.append(note("unknown_variant", "algorithms: '{name}' has no variant '{variant}'; it has {known}",
                                 name=name, variant=variant, known=algorithm.variants))
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
        problems.append(note("indicators_unavailable",
                             "indicators: {wrong} are not available for a {kind} project; choose from {allowed}",
                             wrong=wrong, kind=kind, allowed=list(allowed),
                             multiobjective=manifest.is_multiobjective))
    if "gap" in indicators and not manifest.is_multiobjective:
        no_optimum = [i.name for i in instances if i.optimum is None]
        if no_optimum:
            problems.append(note("gap_needs_optimum",
                                 "indicators: 'gap' needs a known optimum, missing for instances {missing}",
                                 missing=no_optimum))

    parameters = _resolve_parameters(setup, manifest, units, problems)
    if problems:
        raise PlanError(problems)
    return Plan(instances=instances, units=units, seeds=setup.seed_list, indicators=list(indicators),
                tuning_instances=tuning_instances, parameters=parameters)


def _check_bounds(setup: Setup, manifest: Manifest, tuning_instances, problems) -> None:
    bounds = setup.tuning.bounds
    if not bounds:
        return
    if not manifest.is_multiobjective:
        problems.append(note("bounds_single_objective", "tuning.bounds: only used by multi-objective projects"))
        return
    names = {i.name for i in tuning_instances}
    for instance, pairs in bounds.items():
        if instance not in names:
            problems.append(note("bounds_not_training",
                                 "tuning.bounds: '{instance}' is not a training instance; they are {known}",
                                 instance=instance, known=sorted(names)))
        elif len(pairs) != len(manifest.objectives):
            problems.append(note("bounds_count",
                                 "tuning.bounds.{instance}: needs one [min, max] per objective ({expected}), got {got}",
                                 instance=instance, expected=len(manifest.objectives), got=len(pairs)))
        elif any(not low <= high for low, high in pairs):
            problems.append(note("bounds_order",
                                 "tuning.bounds.{instance}: every pair must be [min, max] with min <= max",
                                 instance=instance))


def tuned_parameter_names(setup: Setup, manifest: Manifest, algorithm: str, variant: str) -> list[str]:
    """Parameters the tuner searches for one unit: all of the algorithm's, except those fixed in the setup."""
    fixed = set(setup.parameters.get(algorithm, {})) | set(setup.parameters.get(f"{algorithm}/{variant}", {}))
    return [p.name for p in manifest.algorithm(algorithm).parameters if p.name not in fixed]


def _resolve_parameters(setup: Setup, manifest: Manifest, units, problems) -> dict:
    for key, values in setup.parameters.items():
        name, _, variant = key.partition("/")
        algorithm = next((a for a in manifest.algorithms if a.name == name), None)
        if algorithm is None or (variant and variant not in algorithm.variants):
            problems.append(note("param_unknown_key",
                                 "parameters: '{key}' is not an algorithm (or algorithm/variant) of the project",
                                 key=key))
            continue
        space = {p.name: p for p in algorithm.parameters}
        for pname, value in values.items():
            if pname not in space:
                problems.append(note("param_unknown_name",
                                     "parameters: '{key}' has no parameter '{name}'; it has {known}",
                                     key=key, name=pname, known=sorted(space)))
                continue
            error = space[pname].value_error(value)
            if error:
                problems.append(under(f"parameters: {key}.{pname}", error))
    resolved = {}
    for name, variant in units:
        algorithm = manifest.algorithm(name)
        values = {p.name: p.default for p in algorithm.parameters if p.default is not None}
        values.update(setup.parameters.get(name, {}))
        values.update(setup.parameters.get(f"{name}/{variant}", {}))
        resolved[(name, variant)] = values
    return resolved
