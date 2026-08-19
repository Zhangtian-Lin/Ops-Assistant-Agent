"""项目所需 JSON Schema 子集校验器，默认拒绝未声明字段。"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


def validate_schema(value: Any, schema: Dict[str, Any], path: str = "$") -> Optional[str]:
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            return f"{path} must be an object"
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                return f"{path}.{required} is required"
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            if extra:
                return f"{path} contains unknown fields: {', '.join(sorted(extra))}"
        for key, item in value.items():
            if key in properties:
                error = validate_schema(item, properties[key], f"{path}.{key}")
                if error:
                    return error
        return None
    if expected == "string":
        if not isinstance(value, str):
            return f"{path} must be a string"
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 2**31):
            return f"{path} has invalid length"
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            return f"{path} has invalid format"
        if "enum" in schema and value not in schema["enum"]:
            return f"{path} is not an allowed value"
        return None
    if expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"{path} must be an integer"
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            return f"{path} is outside the allowed range"
        return None
    if expected == "boolean" and not isinstance(value, bool):
        return f"{path} must be a boolean"
    if expected == "array" and not isinstance(value, list):
        return f"{path} must be an array"
    return None
