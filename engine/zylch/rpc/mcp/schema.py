from typing import Any

from zylch.workflows.errors import WorkflowError


def string(limit: int = 128, minimum: int = 1) -> dict[str, Any]:
    return {"type": "string", "minLength": minimum, "maxLength": limit}


def integer(maximum: int, minimum: int = 0) -> dict[str, Any]:
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def object_schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def validate(value: Any, schema: dict[str, Any]) -> None:
    kind = schema["type"]
    valid = True
    if kind == "object":
        valid = isinstance(value, dict)
        if valid:
            properties = schema.get("properties", {})
            valid = not set(schema.get("required", ())) - value.keys()
            if schema.get("additionalProperties") is False:
                valid = valid and not value.keys() - properties.keys()
            if valid:
                for key, item in value.items():
                    if key in properties:
                        validate(item, properties[key])
                    elif isinstance(schema.get("additionalProperties"), dict):
                        validate(item, schema["additionalProperties"])
            valid = valid and len(value) <= schema.get("maxProperties", 128)
    elif kind == "array":
        valid = isinstance(value, list) and len(value) <= schema.get("maxItems", 128)
        if valid:
            for item in value:
                validate(item, schema["items"])
    elif kind == "string":
        valid = isinstance(value, str) and schema.get("minLength", 0) <= len(value) <= schema.get(
            "maxLength", 65536
        )
    elif kind == "integer":
        valid = type(value) is int and schema.get("minimum", 0) <= value <= schema.get(
            "maximum", 2147483647
        )
    elif kind == "boolean":
        valid = type(value) is bool
    if not valid:
        raise WorkflowError("invalid_input")
