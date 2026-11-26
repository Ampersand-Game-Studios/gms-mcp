"""The input schema a client is shown for each tool, without what it does not need.

Clients send every tool's input schema to the model at the start of each session, so each word
in it is paid for once per session. Pydantic writes some that carry no information:

- a ``title`` on the schema and on every property, made from the name ("Test Code" for
  ``test_code``);
- ``anyOf: [<type>, {"type": "null"}]`` with ``"default": null`` for an optional argument,
  where leaving the argument out already means the same;
- ``project_root``, which can only ever name the one project this server is pinned to and
  defaults to it;
- ``prefer_cli`` and ``quiet``, which no agent was seen to pass in 416 recorded calls
  (``quiet`` repeats ``output_mode``, and ``prefer_cli`` only picks an internal route).

Arguments are still validated against the function's own signature, so a call that passes
``null`` or a hidden argument is accepted exactly as before.
"""

from __future__ import annotations

from typing import Any

_NULL = {"type": "null"}
_OUTPUT_MODE_ARGS = frozenset({"output_mode", "tail_lines"})
OUTPUT_MODE_TOOLS = frozenset({"gm_compile", "gm_run", "gm_run_stop", "gm_run_status"})
HIDDEN_ARGUMENTS = frozenset(
    {
        "project_root",
        "prefer_cli",
        "quiet",
        "output_mode",
        "tail_lines",
        "skip_maintenance",
        "no_auto_fix",
        "maintenance_verbose",
    }
)


def _compact(node: Any) -> Any:
    if isinstance(node, list):
        return [_compact(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {key: _compact(value) for key, value in node.items() if key != "title" or not isinstance(value, str)}
    any_of = out.get("anyOf")
    if isinstance(any_of, list) and len(any_of) == 2 and _NULL in any_of and out.get("default", 0) is None:
        (other,) = [option for option in any_of if option != _NULL]
        merged = {key: value for key, value in out.items() if key not in ("anyOf", "default")}
        return {**other, **merged}
    return out


def compact_input_schema(schema: dict[str, Any], *, tool_name: str | None = None) -> dict[str, Any]:
    """Return ``schema`` with generated titles, optional-null wrappers and hidden arguments removed."""
    out = _compact(schema)
    properties = out.get("properties")
    if isinstance(properties, dict):
        to_hide = HIDDEN_ARGUMENTS - (_OUTPUT_MODE_ARGS if tool_name in OUTPUT_MODE_TOOLS else frozenset())
        # A hidden argument that HTTP clients route as a header (x-mcp-header) has to stay listed.
        hidden = {
            name
            for name, value in properties.items()
            if name in to_hide and not (isinstance(value, dict) and "x-mcp-header" in value)
        }
        out["properties"] = {name: value for name, value in properties.items() if name not in hidden}
        required = [name for name in out.get("required", []) if name not in hidden]
        if required:
            out["required"] = required
        else:
            out.pop("required", None)
    return out
