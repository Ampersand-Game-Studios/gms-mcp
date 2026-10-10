"""GameMaker-native JSON layout (the compact ``.yy`` / ``.yyp`` format written by 2023.x - LTS 2026).

GameMaker does not write generic pretty-printed JSON. Its layout is:

* every member ends with a comma, including the last one;
* there is no space after ``:`` and no trailing newline;
* objects are written one member per line until an array is entered; from then on
  objects are written on a single line (``{"id":{"name":"a","path":"b",},},``);
* keyed dictionaries (``ConfigValues``, keyframe ``Channels``) stay one member per line
  even inside an array element;
* arrays put each element on its own line (a few fixed-size numeric arrays such as
  extension function ``args`` stay inline; IDEs before 2024 kept every scalar array inline);
* font ``glyphs`` are one glyph per line;
* indentation is two spaces per nesting level, counting inline levels too.

Re-rendering one of these files with ``json.dumps(indent=2)`` rewrites every line, which
breaks line-based merges and the tools other people run against the same project. The
functions here let callers keep the native layout byte-for-byte:

    text = path.read_text()
    layout = detect_layout(text)
    if layout is not None:
        path.write_text(dumps(new_data, layout))

``detect_layout`` is a proof, not a guess: a file is treated as native only when
re-rendering its own unmodified data reproduces the original bytes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# Dictionaries whose keys are data (config names, channel indices) rather than a fixed
# schema. GameMaker always writes these one member per line.
_KEYED_DICTIONARIES = frozenset({"ConfigValues", "Channels"})

# Dictionaries whose values are records written on one line each.
_RECORD_DICTIONARIES = frozenset({"glyphs"})
# Fixed-shape numeric arrays that every observed IDE version keeps on one line.
_ALWAYS_INLINE_ARRAYS = frozenset({"args", "guideColour"})

_INDENT = "  "


@dataclass(frozen=True)
class Layout:
    """The writer variant that reproduces one file exactly."""

    newline: str = "\n"
    final_newline: bool = False
    # IDEs before 2024 wrote every scalar array inline; later ones expand them.
    inline_scalar_arrays: bool = False
    # 2024.x IDEs kept keyframe ``Channels`` on the keyframe's own line.
    inline_channels: bool = False


DEFAULT_LAYOUT = Layout()


class GMFloat(float):
    """A float that remembers how GameMaker spelled it (``100.0``, ``1E-05``, ``0.50``)."""

    __slots__ = ("gm_text",)

    def __new__(cls, text: str) -> "GMFloat":
        value = super().__new__(cls, text)
        value.gm_text = text
        return value

    def __reduce__(self):  # pragma: no cover - pickling support for worker hand-off
        return (GMFloat, (self.gm_text,))


def _strip_trailing_commas(raw_text: str) -> str:
    from .utils import strip_trailing_commas

    return strip_trailing_commas(raw_text)


def loads(text: str) -> Any:
    """Parse GameMaker JSON (trailing commas allowed) keeping float spellings."""
    try:
        return json.loads(text, parse_float=GMFloat)
    except json.JSONDecodeError:
        return json.loads(_strip_trailing_commas(text), parse_float=GMFloat)


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, GMFloat):
        return value.gm_text
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("GameMaker JSON cannot represent NaN or infinity")
        text = repr(value)
        # GameMaker always writes a decimal point for real-typed fields.
        return text if any(marker in text for marker in ".eE") else f"{text}.0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f"Cannot serialise {type(value).__name__} as GameMaker JSON")


def _is_container(value: Any) -> bool:
    return isinstance(value, (dict, list, tuple))


def _render(value: Any, depth: int, in_array: bool, key: str, parent_key: str, layout: Layout, out: list[str]) -> None:
    newline = layout.newline
    if isinstance(value, dict):
        if not value:
            out.append("{}")
            return
        expanded = (
            (not in_array)
            or (key in _KEYED_DICTIONARIES and not (key == "Channels" and layout.inline_channels))
            or parent_key == "ConfigValues"
        )
        if expanded:
            inner = _INDENT * (depth + 1)
            out.append("{" + newline)
            children_inline = in_array or key in _RECORD_DICTIONARIES
            for member, child in value.items():
                out.append(f"{inner}{json.dumps(str(member), ensure_ascii=False)}:")
                _render(child, depth + 1, children_inline, str(member), key, layout, out)
                out.append("," + newline)
            out.append(_INDENT * depth + "}")
        else:
            out.append("{")
            for member, child in value.items():
                out.append(f"{json.dumps(str(member), ensure_ascii=False)}:")
                _render(child, depth + 1, in_array, str(member), key, layout, out)
                out.append(",")
            out.append("}")
        return
    if isinstance(value, (list, tuple)):
        if not value:
            out.append("[]")
            return
        if not any(_is_container(child) for child in value) and (
            layout.inline_scalar_arrays or key in _ALWAYS_INLINE_ARRAYS
        ):
            out.append("[" + "".join(_scalar(child) + "," for child in value) + "]")
            return
        inner = _INDENT * (depth + 1)
        out.append("[" + newline)
        for child in value:
            out.append(inner)
            _render(child, depth + 1, True, "", key, layout, out)
            out.append("," + newline)
        out.append(_INDENT * depth + "]")
        return
    out.append(_scalar(value))


def dumps(data: Any, layout: Layout = DEFAULT_LAYOUT) -> str:
    """Render ``data`` in GameMaker's native layout."""
    out: list[str] = []
    _render(data, 0, False, "", "", layout, out)
    if layout.final_newline:
        out.append(layout.newline)
    return "".join(out)


def detect_layout(text: str, data: Any | None = None) -> Layout | None:
    """Return the layout that reproduces ``text`` exactly, or None if it is not native."""
    if not text or text[0] != "{":
        return None
    try:
        parsed = loads(text) if data is None else data
    except ValueError:
        return None
    newline = "\r\n" if "\r\n" in text else "\n"
    final_newline = text.endswith(newline)
    for inline_scalar_arrays, inline_channels in ((False, False), (False, True), (True, False), (True, True)):
        layout = Layout(
            newline=newline,
            final_newline=final_newline,
            inline_scalar_arrays=inline_scalar_arrays,
            inline_channels=inline_channels,
        )
        try:
            if dumps(parsed, layout) == text:
                return layout
        except (ValueError, TypeError):
            return None
    return None


def is_native_layout(text: str, data: Any | None = None) -> bool:
    """True when ``text`` is exactly what GameMaker's writer produces for its data."""
    return detect_layout(text, data) is not None


def looks_like_modern_resource(data: Any) -> bool:
    """A resource authored by a 2023.x+ IDE carries a ``$GM...`` type tag."""
    return isinstance(data, dict) and any(isinstance(key, str) and key.startswith("$") for key in data)


def detect_newline(text: str) -> str:
    """Line ending used by ``text`` (GameMaker on Windows writes CRLF)."""
    return "\r\n" if "\r\n" in text else "\n"
