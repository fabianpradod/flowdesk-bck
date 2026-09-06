from types import UnionType
from typing import Union, get_args, get_origin

from pydantic import BaseModel, model_validator


class StrippedModel(BaseModel):
    """Trims surrounding whitespace on every string field before validation.

    Pydantic applies `min_length` to the raw value, so without this a name or a
    SKU sent as "   " satisfies `min_length=1` and reaches the database blank.
    Stripping first turns it into "", which fails the constraint.

    An empty result collapses to None only when the field is nullable *and*
    carries no `min_length`. That distinction matters: `nombre` and `sku` are
    `str | None` on the update schemas but NOT NULL in the database, so turning
    a blank into None there would swap a clean 422 for a write that fails at the
    column. Their `min_length=1` marks them, and they keep the "" that rejects.
    """

    @model_validator(mode="before")
    @classmethod
    def _strip_text_fields(cls, data):
        if not isinstance(data, dict):
            return data

        cleaned = {}
        for key, value in data.items():
            if isinstance(value, str):
                value = value.strip()
                if not value and _is_nullable_free_text(cls, key):
                    value = None
            cleaned[key] = value
        return cleaned


def _is_nullable_free_text(model: type[BaseModel], field_name: str) -> bool:
    field = model.model_fields.get(field_name)
    if field is None:
        return False
    if any(getattr(item, "min_length", None) for item in field.metadata):
        return False
    return _accepts_none(field.annotation)


def _accepts_none(annotation) -> bool:
    if get_origin(annotation) in (Union, UnionType):
        return type(None) in get_args(annotation)
    return annotation is type(None)
