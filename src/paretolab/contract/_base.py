"""Shared building blocks for the contract models."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

#: Names end up in folder names and command lines, so they are restricted to a safe alphabet.
NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
Name = Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
Sense = Literal["min", "max"]
SCHEMA_VERSION = 1


class Strict(BaseModel):
    """Base model that rejects unknown keys, so typos in YAML files are reported instead of ignored."""

    model_config = ConfigDict(extra="forbid")


def duplicates(items) -> list:
    seen, dup = set(), []
    for item in items:
        if item in seen and item not in dup:
            dup.append(item)
        seen.add(item)
    return dup
