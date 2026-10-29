"""Minimal JSON-Schema-subset validator (stdlib only).

Schemas live in engine/schemas/*.schema.yaml. Unknown keywords raise
SchemaError so a typo can never turn into a silently skipped check.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

__all__ = ["SchemaError", "validate"]


class SchemaError(ValueError):
    pass


_KNOWN = {
    "title", "description", "default", "examples", "$defs", "$ref",
    "type", "enum", "const", "pattern", "minLength", "maxLength", "format",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "required", "properties", "additionalProperties", "propertyNames",
    "items", "minItems", "maxItems", "uniqueItems",
}

_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _type_name(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _is_type(v: Any, t: str) -> bool:
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    return _type_name(v) == t


def _format_ok(v: str, fmt: str) -> bool:
    try:
        if fmt == "date":
            if not _DATE_RE.match(v):
                return False
            date.fromisoformat(v)
            return True
        if fmt == "date-time":
            if not _DATETIME_RE.match(v):
                return False
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return True
    except ValueError:
        return False
    raise SchemaError(f"unsupported format {fmt!r}")


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise SchemaError(f"only local $ref supported, got {ref!r}")
    node: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise SchemaError(f"unresolvable $ref {ref!r}")
        node = node[part]
    return node


def _walk(inst: Any, sch: dict, root: dict, path: str, errs: list[str]) -> None:
    for k in sch:
        if k not in _KNOWN:
            raise SchemaError(f"unsupported schema keyword {k!r}")
    if "$ref" in sch:
        _walk(inst, _resolve(sch["$ref"], root), root, path, errs)
        return

    t = sch.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_is_type(inst, x) for x in types):
            errs.append(f"{path}: expected {'|'.join(types)}, got {_type_name(inst)}")
            return
    if "const" in sch and (inst != sch["const"] or _type_name(inst) != _type_name(sch["const"])):
        errs.append(f"{path}: must equal {sch['const']!r}")
    if "enum" in sch and inst not in sch["enum"]:
        errs.append(f"{path}: {inst!r} not in {sch['enum']}")

    if isinstance(inst, str):
        if "minLength" in sch and len(inst) < sch["minLength"]:
            errs.append(f"{path}: shorter than {sch['minLength']} characters")
        if "maxLength" in sch and len(inst) > sch["maxLength"]:
            errs.append(f"{path}: longer than {sch['maxLength']} characters")
        if "pattern" in sch and not re.search(sch["pattern"], inst):
            errs.append(f"{path}: {inst!r} does not match {sch['pattern']}")
        if "format" in sch and not _format_ok(inst, sch["format"]):
            errs.append(f"{path}: {inst!r} is not a valid {sch['format']}")

    if _is_type(inst, "number"):
        if "minimum" in sch and inst < sch["minimum"]:
            errs.append(f"{path}: {inst} < minimum {sch['minimum']}")
        if "maximum" in sch and inst > sch["maximum"]:
            errs.append(f"{path}: {inst} > maximum {sch['maximum']}")
        if "exclusiveMinimum" in sch and inst <= sch["exclusiveMinimum"]:
            errs.append(f"{path}: {inst} <= exclusiveMinimum {sch['exclusiveMinimum']}")
        if "exclusiveMaximum" in sch and inst >= sch["exclusiveMaximum"]:
            errs.append(f"{path}: {inst} >= exclusiveMaximum {sch['exclusiveMaximum']}")

    if isinstance(inst, dict):
        props = sch.get("properties", {})
        for req in sch.get("required", []):
            if req not in inst:
                errs.append(f"{path}: missing required key {req!r}")
        if "propertyNames" in sch:
            for key in inst:
                sub: list[str] = []
                _walk(key, sch["propertyNames"], root, f"{path}.<key {key!r}>", sub)
                errs.extend(sub)
        addl = sch.get("additionalProperties", True)
        for key, val in inst.items():
            p = f"{path}.{key}"
            if key in props:
                _walk(val, props[key], root, p, errs)
            elif addl is False:
                errs.append(f"{path}: unexpected key {key!r}")
            elif isinstance(addl, dict):
                _walk(val, addl, root, p, errs)

    if isinstance(inst, list):
        if "minItems" in sch and len(inst) < sch["minItems"]:
            errs.append(f"{path}: needs at least {sch['minItems']} items")
        if "maxItems" in sch and len(inst) > sch["maxItems"]:
            errs.append(f"{path}: allows at most {sch['maxItems']} items")
        if sch.get("uniqueItems"):
            seen = []
            for item in inst:
                if item in seen:
                    errs.append(f"{path}: duplicate item {item!r}")
                seen.append(item)
        if "items" in sch:
            for idx, item in enumerate(inst):
                _walk(item, sch["items"], root, f"{path}[{idx}]", errs)


def validate(instance: Any, schema: dict) -> list[str]:
    """Return a list of human-readable errors (empty list means valid)."""
    errs: list[str] = []
    _walk(instance, schema, schema, "$", errs)
    return errs
