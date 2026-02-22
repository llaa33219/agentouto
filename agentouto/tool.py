from __future__ import annotations

import enum
import inspect
from dataclasses import dataclass
from typing import Annotated, Any, Callable, Literal, get_args, get_origin, get_type_hints

from agentouto.context import Attachment

_PYTHON_TYPE_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _build_parameters_schema(func: Callable[..., Any]) -> dict[str, Any]:
    hints = get_type_hints(func, include_extras=True)
    sig = inspect.signature(func)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        annotation = hints.get(name, str)
        prop: dict[str, Any] = {}

        if get_origin(annotation) is Annotated:
            args = get_args(annotation)
            annotation = args[0]
            for metadata in args[1:]:
                if isinstance(metadata, str):
                    prop["description"] = metadata
                    break

        if get_origin(annotation) is Literal:
            values = get_args(annotation)
            if values:
                prop["type"] = _PYTHON_TYPE_TO_JSON.get(type(values[0]), "string")
                prop["enum"] = list(values)
            else:
                prop["type"] = "string"
        elif isinstance(annotation, type) and issubclass(annotation, enum.Enum):
            members = list(annotation)
            if members:
                prop["type"] = _PYTHON_TYPE_TO_JSON.get(type(members[0].value), "string")
            else:
                prop["type"] = "string"
            prop["enum"] = [e.value for e in annotation]
        else:
            prop["type"] = _PYTHON_TYPE_TO_JSON.get(annotation, "string")

        if param.default is not inspect.Parameter.empty:
            default_val = param.default
            if isinstance(default_val, enum.Enum):
                default_val = default_val.value
            prop["default"] = default_val
        else:
            required.append(name)

        properties[name] = prop

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


@dataclass
class ToolResult:
    content: str
    attachments: list[Attachment] | None = None


class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]

    def __init__(self, func: Callable[..., Any]) -> None:
        self.func = func
        self.name = func.__name__
        self.description = (func.__doc__ or "").strip()
        self.parameters = _build_parameters_schema(func)

    async def execute(self, **kwargs: Any) -> str | ToolResult:
        result = self.func(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, ToolResult):
            return result
        return str(result)

    def to_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
