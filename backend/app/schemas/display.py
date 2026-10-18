"""Server-side display strings for response schemas (spec 013a section 4): every marked field `x` gains `x_display`.

The raw field is untouched; the sibling is added at serialization. A missing value shows "Unavailable" and gets
`x_unavailable_reason`. Imports domain only (schemas -> domain), the formatters live in `domain/display.py`.
"""

import typing
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, model_serializer

from app.domain import display as fmt


@dataclass(frozen=True)
class DisplayKind:
    """Annotated metadata: how the field is shown (`inr`, `price`, `plain` or `datetime`)."""

    kind: str


def _kind_of(hint) -> str | None:
    stack = [hint]
    while stack:
        h = stack.pop()
        if typing.get_origin(h) is typing.Annotated:
            args = typing.get_args(h)
            for meta in args[1:]:
                if isinstance(meta, DisplayKind):
                    return meta.kind
            stack.append(args[0])
        elif typing.get_origin(h) is not None:
            stack.extend(typing.get_args(h))
    return None


class WithDisplay(BaseModel):
    @classmethod
    def display_fields(cls) -> dict[str, str]:
        hints = typing.get_type_hints(cls, include_extras=True)
        return {n: k for n in cls.model_fields if (k := _kind_of(hints.get(n))) is not None}

    def unavailable_reasons(self) -> dict[str, str]:
        """Field -> why it is missing, for nullable fields; a subclass overrides it."""
        return {}

    def display_notes(self) -> dict[str, str]:
        """Field -> a short note appended to its display, e.g. "(partial: 1 of 2 holdings valued)"."""
        return {}

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        """Serialization schemas list the `x_display` / `x_unavailable_reason` siblings the wrap serializer adds (OpenAPI)."""
        schema = handler(core_schema)
        if handler.mode != "serialization":
            return schema
        resolved = handler.resolve_ref_schema(schema)
        props, required = resolved.setdefault("properties", {}), resolved.setdefault("required", [])
        for name in cls.display_fields():
            props[f"{name}_display"] = {"type": "string", "title": f"{name} display"}
            props[f"{name}_unavailable_reason"] = {"anyOf": [{"type": "string"}, {"type": "null"}], "title": f"{name} unavailable reason"}
            required.append(f"{name}_display")
        return schema

    def withheld_displays(self) -> dict[str, str]:
        """Field -> why its value must not be shown even though it is set (e.g. a stored 0 that means "unknown")."""
        return {}

    @model_serializer(mode="wrap")
    def _add_display(self, handler):
        data = handler(self)
        reasons, withheld, notes = self.unavailable_reasons(), self.withheld_displays(), self.display_notes()
        for name, kind in self.display_fields().items():
            value = getattr(self, name)
            if name in withheld:
                data[f"{name}_display"] = fmt.UNAVAILABLE
                data[f"{name}_unavailable_reason"] = withheld[name]
            elif value is None:
                data[f"{name}_display"] = fmt.UNAVAILABLE
                data[f"{name}_unavailable_reason"] = reasons.get(name, "not available")
            elif kind == "datetime":
                data[f"{name}_display"] = fmt.format_datetime_ist(typing.cast(datetime, value))
            else:
                data[f"{name}_display"] = fmt.number(typing.cast(Decimal, value), kind)["display"] + notes.get(name, "")
        return data
