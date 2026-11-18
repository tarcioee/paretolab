"""Reading and writing contract files with readable error messages."""
import json
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from paretolab.contract.manifest import Manifest
from paretolab.contract.result import RunOutput, RunResult
from paretolab.contract.setup import Plan, PlanError, Setup, make_plan

M = TypeVar("M", bound=BaseModel)


class ContractError(Exception):
    """A contract file is missing, unreadable or invalid. The message is meant for the user."""


def describe(error: ValidationError) -> str:
    lines = []
    for e in error.errors():
        where = ".".join(str(part) for part in e["loc"]) or "(top level)"
        message = e["msg"].removeprefix("Value error, ")
        lines.append(f"  - {where}: {message}")
    return "\n".join(lines)


def read_data(path) -> object:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"{path}: cannot read ({exc.strerror or exc})") from None
    try:
        return json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        kind = "JSON" if path.suffix.lower() == ".json" else "YAML"
        raise ContractError(f"{path}: not valid {kind}\n  {exc}") from None


def load_model(path, model: type[M]) -> M:
    data = read_data(path)
    if not isinstance(data, dict):
        raise ContractError(f"{path}: expected a mapping at the top level")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ContractError(f"{path}: invalid {model.__name__}\n{describe(exc)}") from None


def load_manifest(path) -> Manifest:
    return load_model(path, Manifest)


def load_experiment(setup_path) -> tuple[Setup, Manifest, Plan]:
    """Load a setup, the manifest it points to (relative to the setup file) and the resolved plan."""
    setup = load_model(setup_path, Setup)
    manifest = load_manifest(Path(setup_path).parent / setup.project)
    try:
        plan = make_plan(setup, manifest)
    except PlanError as exc:
        raise ContractError(f"{setup_path}: does not match the project '{manifest.name}'\n"
                            + "\n".join(f"  - {line}" for line in str(exc).splitlines())) from None
    return setup, manifest, plan


def load_output(path, manifest: Manifest = None) -> RunOutput:
    output = load_model(path, RunOutput)
    if manifest is not None:
        try:
            output.check_against(manifest)
        except ValueError as exc:
            raise ContractError(f"{path}: {exc}") from None
    return output


def write_result(path, result: RunResult) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(result.model_dump_json(indent=1, exclude_none=True), encoding="utf-8")
    tmp.replace(path)
