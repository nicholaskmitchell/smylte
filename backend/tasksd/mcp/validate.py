"""Enforce the JSON Schema each tool already advertises.

`tools/list` publishes a schema per tool, but a client is not obliged to honour
it and a compromised or simply buggy one will not. Everything downstream —
`TaskService`, the scheduling maths, the iCalendar writer — was written behind
FastAPI, where pydantic had already checked bounds; reaching it from here
without an equivalent check meant the advertised contract was decoration.

It cost a real defect: `duration_minutes: 0` on a booking link passed straight
through to `generate_slots`, whose cursor advances by that duration and so never
terminates — inside the service lock, from a value already persisted. The HTTP
route for the same table had the bound; this path did not.

A small validator rather than the `jsonschema` package: the subset the tool
table actually uses is type, enum, minimum/maximum, minLength/maxLength, pattern
and array items, and a dependency in the request path of a security-sensitive
endpoint should earn its place. Anything the schemas do not use is not
implemented — and `_assert_supported` fails loudly in the tests if a schema ever
grows a keyword this cannot enforce, so the gap cannot open silently.
"""
from __future__ import annotations

import re

# Keywords this validator understands. A schema using anything else would be
# silently unenforced, which is exactly the failure being fixed here — so the
# test suite asserts every tool schema stays inside this set.
SUPPORTED = frozenset({
    "type", "properties", "required", "additionalProperties", "description",
    "enum", "default", "items", "minimum", "maximum",
    "minLength", "maxLength", "pattern", "title",
})

_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "boolean": bool,
    "object": dict,
    "array": list,
    "integer": int,
    "number": (int, float),
}


class SchemaError(ValueError):
    """A value the advertised schema does not allow."""


def _type_ok(value, kind: str) -> bool:
    if kind == "integer":
        # `bool` is an int subclass, and JSON `true` would otherwise satisfy an
        # integer field — the same trap the settings TTL check calls out.
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    expected = _TYPES.get(kind)
    return expected is None or isinstance(value, expected)


def check_value(value, schema: dict, *, where: str) -> None:
    kind = schema.get("type")
    if kind and not _type_ok(value, kind):
        raise SchemaError(f"{where} must be {'an' if kind[0] in 'aio' else 'a'} {kind}")

    choices = schema.get("enum")
    if choices is not None and value not in choices:
        raise SchemaError(f"{where} must be one of: {', '.join(map(str, choices))}")

    if isinstance(value, str):
        lo, hi = schema.get("minLength"), schema.get("maxLength")
        if lo is not None and len(value) < lo:
            raise SchemaError(f"{where} must be at least {lo} character(s)")
        if hi is not None and len(value) > hi:
            raise SchemaError(f"{where} must be at most {hi} characters")
        pattern = schema.get("pattern")
        if pattern is not None and not re.search(pattern, value):
            raise SchemaError(f"{where} is not in the expected format ({pattern})")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        lo, hi = schema.get("minimum"), schema.get("maximum")
        if lo is not None and value < lo:
            raise SchemaError(f"{where} must be at least {lo}")
        if hi is not None and value > hi:
            raise SchemaError(f"{where} must be at most {hi}")

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            check_value(item, schema["items"], where=f"{where}[{i}]")


def check_arguments(args: dict, schema: dict, *, tool: str) -> None:
    """Validate a tools/call argument bag against the tool's advertised schema.

    Unknown and missing keys are reported first and in full, so a client gets
    one message naming everything wrong rather than discovering the arguments
    one rejected call at a time.
    """
    props: dict = schema.get("properties", {})
    unknown = sorted(set(args) - set(props))
    if unknown:
        raise SchemaError(
            f"{tool} has no argument(s) {', '.join(unknown)}. "
            f"It accepts: {', '.join(sorted(props)) or 'no arguments'}."
        )
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        raise SchemaError(f"{tool} is missing required argument(s): {', '.join(missing)}.")
    for key, value in args.items():
        check_value(value, props[key], where=f"{tool}.{key}")


def unsupported_keywords(schema: dict) -> set[str]:
    """Every keyword in `schema` this validator would silently ignore."""
    found: set[str] = set(schema) - SUPPORTED
    for sub in schema.get("properties", {}).values():
        if isinstance(sub, dict):
            found |= unsupported_keywords(sub)
    items = schema.get("items")
    if isinstance(items, dict):
        found |= unsupported_keywords(items)
    return found
