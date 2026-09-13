"""Deriving PATCH bodies from create schemas.

Reusing a create schema for PATCH makes a partial edit fail validation on the
fields it deliberately left out. Writing a second schema by hand instead means
two definitions that drift. Deriving keeps one source of truth: field names,
types and constraints such as max_length all follow the original.
"""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, create_model


def make_partial(base: type[BaseModel], name: str | None = None) -> type[BaseModel]:
    """A copy of `base` with every field optional and defaulting to None.

    Handlers should apply the result with `model_dump(exclude_unset=True)` so an
    omitted field is left alone rather than overwritten with None.
    """
    fields: dict[str, Any] = {}
    for field_name, field_info in base.model_fields.items():
        optional_info = deepcopy(field_info)
        optional_info.default = None
        fields[field_name] = (field_info.annotation | None, optional_info)
    return create_model(name or f"{base.__name__}Patch", **fields)  # type: ignore[call-overload]
