"""Result of one run.

Two levels:

* :class:`RunOutput` is what the user's program writes: only the solutions and what the program measured itself.
* :class:`RunResult` is what paretolab stores. It adds the run's identity, which paretolab already knows
  (instance, algorithm, variant, seed, parameters and objectives), so programs never have to echo it back.
"""
from typing import Any, Literal

from pydantic import Field, FiniteFloat, model_validator

from paretolab.contract._base import SCHEMA_VERSION, Strict
from paretolab.contract.manifest import Manifest, Objective

Point = list[FiniteFloat]


class TracePoint(Strict):
    evaluations: int | None = Field(None, ge=0)
    time_s: float | None = Field(None, ge=0)
    front: list[Point]


class RunOutput(Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    #: Final solutions as objective vectors, in the order of the project's objectives.
    #: Only feasible solutions; empty when none was found. A single-objective run writes its best value: [[value]].
    front: list[Point]
    #: ok | timeout (the time limit stopped the run; the front is still valid) | error (the front is ignored).
    status: Literal["ok", "timeout", "error"] = "ok"
    evaluations: int | None = Field(None, ge=0)
    wall_time_s: float | None = Field(None, ge=0)
    #: Decision variables, one entry per point of ``front`` (any JSON value).
    variables: list[Any] | None = None
    #: Snapshots during the run, for anytime-performance plots.
    convergence_trace: list[TracePoint] | None = None
    error_message: str | None = None
    #: Free-form data; the core ignores it, plugins may read it.
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self):
        sizes = {len(p) for p in self.front}
        for snapshot in self.convergence_trace or []:
            sizes |= {len(p) for p in snapshot.front}
        if 0 in sizes:
            raise ValueError("front: a point has no objective values")
        if len(sizes) > 1:
            raise ValueError(f"front: points with different numbers of objectives {sorted(sizes)}")
        if self.variables is not None and len(self.variables) != len(self.front):
            raise ValueError(f"variables has {len(self.variables)} entries but front has {len(self.front)} points")
        return self

    @property
    def n_objectives(self) -> int | None:
        return len(self.front[0]) if self.front else None

    def check_against(self, manifest: Manifest) -> None:
        """Raise ValueError if the points do not have one value per objective of ``manifest``."""
        expected = len(manifest.objectives)
        sizes = {len(p) for p in self.front}
        for snapshot in self.convergence_trace or []:
            sizes |= {len(p) for p in snapshot.front}
        if sizes - {expected}:
            raise ValueError(f"the project has {expected} objectives "
                             f"({', '.join(o.name for o in manifest.objectives)}) but the result has points "
                             f"with {sorted(sizes - {expected})}")


class RunResult(RunOutput):
    instance: str
    algorithm: str
    variant: str
    seed: int
    parameters: dict[str, Any] = Field(default_factory=dict)
    objectives: list[Objective] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_dimension(self):
        if self.n_objectives is not None and self.n_objectives != len(self.objectives):
            raise ValueError(f"front has {self.n_objectives} objectives per point but {len(self.objectives)} "
                             f"objectives are declared")
        return self

    @classmethod
    def from_output(cls, output: RunOutput, *, manifest: Manifest, instance: str, algorithm: str, variant: str,
                    seed: int, parameters: dict | None = None) -> "RunResult":
        output.check_against(manifest)
        return cls(**output.model_dump(), instance=instance, algorithm=algorithm, variant=variant, seed=seed,
                   parameters=parameters or {}, objectives=manifest.objectives)
