#!/usr/bin/env python3
"""Token-aware GameMaker asset-reference discovery and rewriting.

GML is rewritten token-by-token so comments, ordinary strings, scoped fields,
and struct keys are not mistaken for asset references. The exact first string
argument to ``asset_get_index`` is treated as an explicit asset reference.
GameMaker JSON is parsed and only resource-reference structures and the
renamed asset's own metadata are updated.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Tuple

from .event_model import rewrite_collision_event_target
from .exceptions import ValidationError
from .transactions import transactional_rename
from .utils import _read_text_preserving_newlines, atomic_write_text, load_json_loose, save_pretty_json_gm


# Tool/VCS caches are never project content, wherever they appear.
_IGNORED_DIRECTORIES = {
    ".git",
    ".gms_mcp",
    ".gms-mcp",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
# Build outputs only exist beside the .yyp; an asset may legitimately be named "build".
_IGNORED_ROOT_DIRECTORIES = {"build", "dist", "node_modules"}

_PROJECT_DIR_PREFIX = "${project_dir}/"


def is_ignored_project_path(relative: Path) -> bool:
    """Return whether a project-relative path is outside scanned project content."""
    parts = relative.parts
    if parts and parts[0] in _IGNORED_ROOT_DIRECTORIES:
        return True
    return any(part in _IGNORED_DIRECTORIES for part in parts)


def read_gml_source(path: Path) -> str:
    """Read GML byte-for-byte (newlines preserved). GameMaker source must be UTF-8."""
    try:
        return _read_text_preserving_newlines(path)
    except UnicodeDecodeError as exc:
        raise ValidationError(f"GML source is not valid UTF-8; fix its encoding before rewriting: {path}") from exc


def load_project_json(path: Path) -> Any:
    """Parse one scanned GameMaker JSON file, refusing to silently skip it."""
    try:
        parsed = load_json_loose(path)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(f"Could not read GameMaker JSON: {path}: {exc}") from exc
    if parsed is None:
        raise ValidationError(f"Could not parse GameMaker JSON; repair it before renaming: {path}")
    return parsed


_ASSET_DIRECTORIES = {
    "animcurve": "animcurves",
    "font": "fonts",
    "folder": "folders",
    "note": "notes",
    "object": "objects",
    "path": "paths",
    "room": "rooms",
    "script": "scripts",
    "sequence": "sequences",
    "shader": "shaders",
    "sound": "sounds",
    "sprite": "sprites",
    "tileset": "tilesets",
    "timeline": "timelines",
}


@dataclass(frozen=True)
class AssetReference:
    """A validated reference that will change during an asset rename."""

    file_path: Path
    line_number: int
    old_text: str
    new_text: str
    reference_type: str
    context: str


@dataclass
class JsonRewriteStats:
    """Counts of structured JSON fields changed by a rewrite."""

    names: int = 0
    paths: int = 0
    expressions: int = 0
    collision_events: int = 0

    @property
    def total(self) -> int:
        return self.names + self.paths + self.expressions + self.collision_events


def _is_identifier_start(char: str) -> bool:
    return char == "_" or char.isalpha()


def _is_identifier_continue(char: str) -> bool:
    return char == "_" or char.isalnum()


def _gml_noncode_spans(source: str) -> List[Tuple[int, int, str]]:
    """Return ordered ``(start, end, kind)`` spans of non-executable GML.

    Kinds are ``comment``, ``string`` (escaped or verbatim literal),
    ``simple_string`` (a closed literal without escapes) and ``template``
    (literal text of a ``$"..."`` template string). String spans include
    their quotes. ``{...}`` interpolations inside template strings are code
    and are scanned recursively, so ``$"hp {oEnemy.hp}"`` exposes ``oEnemy``.
    """

    spans: List[Tuple[int, int, str]] = []
    length = len(source)

    def scan_string(index: int) -> int:
        quote = source[index]
        verbatim = index > 0 and source[index - 1] == "@"
        start = index
        index += 1
        simple = True
        while index < length:
            if source[index] == quote:
                if verbatim and index + 1 < length and source[index + 1] == quote:
                    simple = False
                    index += 2
                    continue
                spans.append((start, index + 1, "simple_string" if simple else "string"))
                return index + 1
            if not verbatim and source[index] == "\\" and index + 1 < length:
                simple = False
                index += 2
                continue
            index += 1
        spans.append((start, length, "string"))
        return length

    def scan_template(index: int) -> int:
        segment_start = index
        index += 1
        while index < length:
            char = source[index]
            if char == '"':
                spans.append((segment_start, index + 1, "template"))
                return index + 1
            if char == "\\" and index + 1 < length:
                index += 2
                continue
            if char == "{":
                spans.append((segment_start, index + 1, "template"))
                closing = scan_code(index + 1, inside_interpolation=True)
                if closing >= length:
                    return length
                segment_start = closing
                index = closing + 1
                continue
            index += 1
        spans.append((segment_start, length, "template"))
        return length

    def scan_code(index: int, *, inside_interpolation: bool) -> int:
        depth = 0
        while index < length:
            if source.startswith("//", index):
                newline = source.find("\n", index + 2)
                end = length if newline < 0 else newline
                spans.append((index, end, "comment"))
                index = end
                continue
            if source.startswith("/*", index):
                closing = source.find("*/", index + 2)
                end = length if closing < 0 else closing + 2
                spans.append((index, end, "comment"))
                index = end
                continue
            char = source[index]
            if char == '"' and index > 0 and source[index - 1] == "$":
                index = scan_template(index)
                continue
            if char in {'"', "'"}:
                index = scan_string(index)
                continue
            if inside_interpolation:
                if char == "{":
                    depth += 1
                elif char == "}":
                    if depth == 0:
                        return index
                    depth -= 1
            index += 1
        return length

    scan_code(0, inside_interpolation=False)
    return spans


def iter_gml_identifier_spans(source: str) -> Iterator[Tuple[int, int, str]]:
    """Yield executable GML identifier spans, excluding comments and strings.

    The scanner deliberately preserves the source byte-for-byte outside the
    returned spans. It understands line comments, block comments, quoted
    strings, escapes, GameMaker verbatim strings (the quote after ``@`` is
    still treated as a string delimiter) and ``$"..."`` template strings,
    whose ``{...}`` interpolations are executable code.
    """

    noncode = iter(_gml_noncode_spans(source))
    next_span = next(noncode, None)
    index = 0
    length = len(source)
    while index < length:
        while next_span is not None and next_span[1] <= index:
            next_span = next(noncode, None)
        if next_span is not None and next_span[0] <= index:
            index = next_span[1]
            continue

        char = source[index]
        if _is_identifier_start(char):
            end = index + 1
            while end < length and _is_identifier_continue(source[end]):
                end += 1
            yield index, end, source[index:end]
            index = end
            continue

        index += 1


def rewrite_gml_identifiers(source: str, replacements: Mapping[str, str]) -> Tuple[str, int]:
    """Rewrite exact executable GML identifiers and return replacement count."""

    pieces: List[str] = []
    cursor = 0
    count = 0
    for start, end, identifier in iter_gml_identifier_spans(source):
        replacement = replacements.get(identifier)
        if replacement is None or replacement == identifier:
            continue
        pieces.append(source[cursor:start])
        pieces.append(replacement)
        cursor = end
        count += 1

    if count == 0:
        return source, 0
    pieces.append(source[cursor:])
    return "".join(pieces), count


def _mask_gml_noncode(source: str) -> str:
    """Replace comments and string contents with spaces while preserving offsets."""
    masked = list(source)
    for start, end, _kind in _gml_noncode_spans(source):
        for position in range(start, end):
            if masked[position] not in {"\n", "\r"}:
                masked[position] = " "
    return "".join(masked)


def _non_whitespace_character(source: str, index: int, direction: int) -> str:
    while 0 <= index < len(source):
        if not source[index].isspace():
            return source[index]
        index += direction
    return ""


def _enum_member_name_spans(masked_source: str) -> set[Tuple[int, int]]:
    """Return identifier spans used as enum member declarations."""
    excluded: set[Tuple[int, int]] = set()
    identifiers = list(iter_gml_identifier_spans(masked_source))
    for index, (_start, end, token) in enumerate(identifiers):
        if token != "enum" or index + 1 >= len(identifiers):
            continue
        cursor = identifiers[index + 1][1]
        while cursor < len(masked_source) and masked_source[cursor].isspace():
            cursor += 1
        if cursor >= len(masked_source) or masked_source[cursor] != "{":
            continue

        cursor += 1
        expect_member = True
        brace_depth = 1
        paren_depth = 0
        bracket_depth = 0
        while cursor < len(masked_source) and brace_depth:
            char = masked_source[cursor]
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    break
            elif brace_depth == 1:
                if char == "(":
                    paren_depth += 1
                elif char == ")" and paren_depth:
                    paren_depth -= 1
                elif char == "[":
                    bracket_depth += 1
                elif char == "]" and bracket_depth:
                    bracket_depth -= 1
                elif paren_depth == 0 and bracket_depth == 0:
                    if char == ",":
                        expect_member = True
                    elif expect_member and _is_identifier_start(char):
                        member_end = cursor + 1
                        while member_end < len(masked_source) and _is_identifier_continue(masked_source[member_end]):
                            member_end += 1
                        excluded.add((cursor, member_end))
                        expect_member = False
                        cursor = member_end
                        continue
            cursor += 1
    return excluded


def _non_asset_identifier_spans(source: str, masked_source: str) -> set[Tuple[int, int]]:
    excluded = _enum_member_name_spans(masked_source)
    identifiers = list(iter_gml_identifier_spans(source))
    offset = 0
    for line in masked_source.splitlines(keepends=True):
        if re.match(r"^\s*#\s*(?:end)?region\b", line):
            line_end = offset + len(line)
            excluded.update((start, end) for start, end, _token in identifiers if offset <= start < line_end)
        offset += len(line)
    return excluded


def find_gml_ambiguous_asset_bindings(source: str, identifier: str) -> List[Tuple[int, str]]:
    """Find declarations or assignments that make a bare asset token ambiguous."""
    masked = _mask_gml_noncode(source)
    escaped = re.escape(identifier)
    findings: set[Tuple[int, str]] = set()

    def add(position: int, reason: str) -> None:
        findings.add((masked.count("\n", 0, position) + 1, reason))

    for declaration in re.finditer(r"\b(?:var|static|globalvar)\b(?P<body>[^;\n]*)", masked):
        body = declaration.group("body")
        segment_start = 0
        paren_depth = 0
        bracket_depth = 0
        brace_depth = 0
        for index, char in enumerate(body + ","):
            if char == "(":
                paren_depth += 1
            elif char == ")" and paren_depth:
                paren_depth -= 1
            elif char == "[":
                bracket_depth += 1
            elif char == "]" and bracket_depth:
                bracket_depth -= 1
            elif char == "{":
                brace_depth += 1
            elif char == "}" and brace_depth:
                brace_depth -= 1
            elif char == "," and paren_depth == bracket_depth == brace_depth == 0:
                segment = body[segment_start:index]
                declared = re.match(r"\s*(?P<name>[A-Za-z_]\w*)", segment)
                if declared and declared.group("name") == identifier:
                    add(
                        declaration.start("body") + segment_start + declared.start("name"),
                        "local or global variable declaration",
                    )
                segment_start = index + 1

    for function in re.finditer(r"\bfunction(?:\s+[A-Za-z_]\w*)?\s*\((?P<body>[^)]*)\)", masked):
        body = function.group("body")
        offset = 0
        for parameter in body.split(","):
            declared = re.match(r"\s*(?P<name>[A-Za-z_]\w*)", parameter)
            if declared and declared.group("name") == identifier:
                add(function.start("body") + offset + declared.start("name"), "function parameter")
            offset += len(parameter) + 1

    binding_patterns = (
        (rf"\bfunction\s+(?P<name>{escaped})\b", "function declaration"),
        (rf"\benum\s+(?P<name>{escaped})\b", "enum declaration"),
        (rf"(?m)^\s*#\s*macro\s+(?P<name>{escaped})\b", "macro declaration"),
        (rf"\bcatch\s*\(\s*(?P<name>{escaped})\b", "catch binding"),
    )
    for pattern, reason in binding_patterns:
        for match in re.finditer(pattern, masked):
            add(match.start("name"), reason)

    enum_members = _enum_member_name_spans(masked)
    assignment_operator = re.compile(r"\s*(?:\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<=|>>=|\+\+|--|=(?!=))")
    for start, end, token in iter_gml_identifier_spans(source):
        if token != identifier or (start, end) in enum_members:
            continue
        if _non_whitespace_character(masked, start - 1, -1) == ".":
            continue
        if assignment_operator.match(masked, end):
            add(start, "assignment target")
            continue
        prefix = masked[:start]
        if re.search(r"(?:\+\+|--)\s*$", prefix):
            add(start, "assignment target")

    return sorted(findings)


def _is_gml_asset_reference_span(
    masked_source: str,
    start: int,
    end: int,
    excluded_spans: set[Tuple[int, int]],
) -> bool:
    if (start, end) in excluded_spans:
        return False
    previous = _non_whitespace_character(masked_source, start - 1, -1)
    following = _non_whitespace_character(masked_source, end, 1)
    # GameMaker permits fields with the same name as an asset. `self.foo`,
    # `global.foo`, arbitrary struct/instance fields, and `{ foo: value }`
    # are variable names, not references to the resource named `foo`.
    if previous == ".":
        return False
    # A colon only denotes a field key when the identifier occupies a key
    # position in a struct/enum literal. `case asset:` and the true arm in
    # `condition ? asset : other` are ordinary asset expressions.
    return not (following == ":" and previous in {"{", ","})


def iter_gml_asset_identifier_spans(source: str, identifier: str) -> Iterator[Tuple[int, int, str]]:
    """Yield bare executable tokens that can resolve to a GameMaker asset."""
    masked = _mask_gml_noncode(source)
    excluded_spans = _non_asset_identifier_spans(source, masked)
    for start, end, token in iter_gml_identifier_spans(source):
        if token == identifier and _is_gml_asset_reference_span(masked, start, end, excluded_spans):
            yield start, end, token


def _iter_gml_string_literal_contents(source: str) -> Iterator[Tuple[int, int, str]]:
    """Yield unescaped simple string contents while excluding comments."""
    for start, end, kind in _gml_noncode_spans(source):
        if kind == "simple_string":
            yield start + 1, end - 1, source[start + 1 : end - 1]


def iter_gml_asset_lookup_string_spans(source: str, identifier: str) -> Iterator[Tuple[int, int, str]]:
    """Yield exact string names passed as the first argument to asset_get_index."""
    masked = _mask_gml_noncode(source)
    for start, end, value in _iter_gml_string_literal_contents(source):
        if value != identifier:
            continue
        prefix = masked[:start].rstrip()
        if prefix.endswith("@"):
            prefix = prefix[:-1].rstrip()
        call = re.search(r"\basset_get_index\s*\(\s*$", prefix)
        if call and _non_whitespace_character(prefix, call.start() - 1, -1) != ".":
            yield start, end, value


def iter_gml_asset_reference_spans(source: str, identifier: str) -> Iterator[Tuple[int, int, str]]:
    """Yield bare resource tokens and explicit name-lookup string arguments."""
    yield from iter_gml_asset_identifier_spans(source, identifier)
    yield from iter_gml_asset_lookup_string_spans(source, identifier)


def rewrite_gml_asset_identifiers(source: str, replacements: Mapping[str, str]) -> Tuple[str, int]:
    """Rewrite eligible asset tokens and asset_get_index string arguments."""
    masked = _mask_gml_noncode(source)
    excluded_spans = _non_asset_identifier_spans(source, masked)
    planned: List[Tuple[int, int, str]] = []
    for start, end, identifier in iter_gml_identifier_spans(source):
        replacement = replacements.get(identifier)
        if (
            replacement is not None
            and replacement != identifier
            and _is_gml_asset_reference_span(masked, start, end, excluded_spans)
        ):
            planned.append((start, end, replacement))
    for identifier, replacement in replacements.items():
        if replacement == identifier:
            continue
        planned.extend(
            (start, end, replacement) for start, end, _value in iter_gml_asset_lookup_string_spans(source, identifier)
        )

    pieces: List[str] = []
    cursor = 0
    count = 0
    for start, end, replacement in sorted(planned):
        pieces.append(source[cursor:start])
        pieces.append(replacement)
        cursor = end
        count += 1
    if count == 0:
        return source, 0
    pieces.append(source[cursor:])
    return "".join(pieces), count


def find_gml_global_declarations(source: str) -> List[Tuple[str, str]]:
    """Return ``(kind, name)`` for globally scoped GML declarations in a script.

    Top-level named functions, macros and enums are global in GameMaker, so a
    copied script would declare them twice.
    """
    masked = _mask_gml_noncode(source)
    declarations: List[Tuple[str, str]] = []
    depth = 0
    cursor = 0
    for match in re.finditer(r"\bfunction\s+(?P<name>[A-Za-z_]\w*)\s*\(", masked):
        depth += masked.count("{", cursor, match.start()) - masked.count("}", cursor, match.start())
        cursor = match.start()
        if depth <= 0:
            declarations.append(("function", match.group("name")))
    for match in re.finditer(r"(?m)^\s*#\s*macro\s+(?:[A-Za-z_]\w*:)?(?P<name>[A-Za-z_]\w*)", masked):
        declarations.append(("macro", match.group("name")))
    for match in re.finditer(r"\benum\s+(?P<name>[A-Za-z_]\w*)", masked):
        declarations.append(("enum", match.group("name")))
    return declarations


def count_gml_identifier(source: str, identifier: str) -> int:
    """Count exact bare executable references to a GameMaker asset."""

    return sum(1 for _span in iter_gml_asset_reference_spans(source, identifier))


def _asset_resource_paths(old_path: str, new_path: str) -> Tuple[str, str, str, str]:
    """Return registered ``.yy`` paths and their asset directories (with ``/``).

    Paths always come from the ``.yyp`` registration: tool-created assets use
    lower-case folders while IDE-created ones keep the asset's exact case.
    """
    old_path = old_path.replace("\\", "/")
    new_path = new_path.replace("\\", "/")
    if old_path.startswith("folders/"):
        return old_path, new_path, "folders/", "folders/"
    old_directory = old_path.rsplit("/", 1)[0] + "/"
    new_directory = new_path.rsplit("/", 1)[0] + "/"
    return old_path, new_path, old_directory, new_directory


def _split_project_dir_prefix(value: str) -> Tuple[str, str]:
    """Split GameMaker's ``${project_dir}/`` macro from a project-relative path."""
    for separator in ("/", "\\"):
        prefix = "${project_dir}" + separator
        if value.startswith(prefix):
            return prefix, value[len(prefix) :]
    return "", value


def _normalized_resource_path(value: str) -> str:
    return _split_project_dir_prefix(value)[1].replace("\\", "/")


def _rewrite_path_string(
    value: str,
    *,
    old_path: str,
    new_path: str,
    old_directory: str,
    new_directory: str,
    own_asset: bool,
) -> str:
    prefix, relative = _split_project_dir_prefix(value)
    windows = "\\" in relative or prefix.endswith("\\")

    def restore(path: str) -> str:
        return prefix + (path.replace("/", "\\") if windows else path)

    normalized = relative.replace("\\", "/")
    if normalized == old_path:
        return restore(new_path)
    if own_asset and old_directory != new_directory and normalized.startswith(old_directory):
        return restore(new_directory + normalized[len(old_directory) :])
    return value


def count_json_resource_references(data: Any, asset_path: str, asset_name: str) -> int:
    """Count exact structured references to one registered GameMaker resource path."""

    normalized_target = asset_path.replace("\\", "/")
    count = 0

    def visit(node: Any) -> None:
        nonlocal count
        if isinstance(node, str):
            if _normalized_resource_path(node) == normalized_target:
                count += 1
            return
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if isinstance(node, dict):
            resource_type = str(node.get("resourceType") or "")
            expression_value = node.get("value")
            if resource_type in {"GMObjectProperty", "GMOverriddenProperty"} and isinstance(expression_value, str):
                count += count_gml_identifier(expression_value, asset_name)
            for key, value in node.items():
                if key == "value" and resource_type in {"GMObjectProperty", "GMOverriddenProperty"}:
                    continue
                visit(value)

    visit(data)
    return count


def rewrite_json_asset_references(
    data: Any,
    old_name: str,
    new_name: str,
    asset_type: str,
    *,
    old_path: str,
    new_path: str,
    own_asset: bool = False,
) -> JsonRewriteStats:
    """Mutate parsed GameMaker JSON using resource-aware rename rules.

    Outside the renamed asset's own ``.yy`` file, a ``name`` is changed only
    when its sibling ``path`` identifies the target resource. Inside the asset,
    exact internal names and resource-directory paths are also updated.
    ``old_path``/``new_path`` are the registered ``.yy`` paths.
    """

    old_path, new_path, old_directory, new_directory = _asset_resource_paths(old_path, new_path)
    stats = JsonRewriteStats()

    def visit(node: Any, location: Tuple[str, ...] = ()) -> None:
        if isinstance(node, list):
            for index, item in enumerate(node):
                if isinstance(item, str):
                    rewritten = _rewrite_path_string(
                        item,
                        old_path=old_path,
                        new_path=new_path,
                        old_directory=old_directory,
                        new_directory=new_directory,
                        own_asset=own_asset,
                    )
                    if rewritten != item:
                        node[index] = rewritten
                        stats.paths += 1
                else:
                    visit(item, location)
            return
        if not isinstance(node, dict):
            return

        if asset_type == "object" and rewrite_collision_event_target(
            node, old_name, new_name, old_path=old_path, new_path=new_path
        ):
            stats.collision_events += 1

        original_path = node.get("path")
        target_resource = isinstance(original_path, str) and _normalized_resource_path(original_path) == old_path
        resource_type = str(node.get("resourceType") or "")
        expression_value = node.get("value")
        if resource_type in {"GMObjectProperty", "GMOverriddenProperty"} and isinstance(expression_value, str):
            rewritten_expression, replacements = rewrite_gml_asset_identifiers(
                expression_value,
                {old_name: new_name},
            )
            if replacements:
                node["value"] = rewritten_expression
                stats.expressions += replacements

        if isinstance(original_path, str):
            rewritten_path = _rewrite_path_string(
                original_path,
                old_path=old_path,
                new_path=new_path,
                old_directory=old_directory,
                new_directory=new_directory,
                own_asset=own_asset,
            )
            if rewritten_path != original_path:
                node["path"] = rewritten_path
                stats.paths += 1

        scoped_property_id = bool(location and location[-1] == "propertyId")
        if target_resource and not scoped_property_id and node.get("name") == old_name:
            node["name"] = new_name
            stats.names += 1

        owns_asset_identity = not location or (asset_type == "sprite" and location == ("sequence",))
        if own_asset and owns_asset_identity:
            for key in ("%Name", "name"):
                if node.get(key) == old_name:
                    node[key] = new_name
                    stats.names += 1

        for key, value in list(node.items()):
            if key == "path" or (key == "value" and resource_type in {"GMObjectProperty", "GMOverriddenProperty"}):
                continue
            if isinstance(value, (dict, list)):
                visit(value, (*location, key))
                continue
            if isinstance(value, str):
                rewritten = _rewrite_path_string(
                    value,
                    old_path=old_path,
                    new_path=new_path,
                    old_directory=old_directory,
                    new_directory=new_directory,
                    own_asset=own_asset,
                )
                if rewritten != value:
                    node[key] = rewritten
                    stats.paths += 1

    visit(data)
    return stats


def plan_collision_file_renames(
    object_yy: Path,
    data: Any,
    old_name: str,
    new_name: str,
    *,
    old_path: str,
    new_path: str,
) -> List[Tuple[Path, Path]]:
    """Plan ``Collision_<old>.gml`` renames for one object's collision events targeting the asset."""
    planned: List[Tuple[Path, Path]] = []

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        candidate = copy.deepcopy(node)
        if rewrite_collision_event_target(candidate, old_name, new_name, old_path=old_path, new_path=new_path):
            source = object_yy.parent / f"Collision_{old_name}.gml"
            destination = object_yy.parent / f"Collision_{new_name}.gml"
            if not source.is_file():
                raise ValidationError(f"Collision event metadata points to missing file: {source}")
            if destination.exists() and destination != source:
                raise ValidationError(f"Collision event rename destination already exists: {destination}")
            pair = (source, destination)
            if pair not in planned:
                planned.append(pair)
        for value in node.values():
            if isinstance(value, (dict, list)):
                visit(value)

    visit(data)
    return planned


class ReferenceScanner:
    """Discover and apply token-aware references for one GameMaker project."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.references: List[AssetReference] = []
        self._old_name: str | None = None
        self._new_name: str | None = None
        self._asset_type: str | None = None
        self._old_path: str | None = None
        self._new_path: str | None = None
        self._collision_file_renames: List[Tuple[Path, Path]] = []

    def _is_ignored(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.project_root)
        except ValueError:
            return True
        return is_ignored_project_path(relative)

    def _is_own_asset_file(self, path: Path, old_path: str, new_path: str) -> bool:
        relative = path.relative_to(self.project_root).as_posix()
        return relative in {old_path.replace("\\", "/"), new_path.replace("\\", "/")}

    def _scanned_json_files(self) -> List[Path]:
        json_files = {
            *self.project_root.rglob("*.yy"),
            *self.project_root.rglob("*.yyp"),
            *self.project_root.rglob("*.resource_order"),
        }
        return sorted(path for path in json_files if not self._is_ignored(path))

    def _scanned_gml_files(self) -> List[Path]:
        return sorted(path for path in self.project_root.rglob("*.gml") if not self._is_ignored(path))

    @staticmethod
    def _line_for(text: str, needle: str) -> int:
        position = text.find(needle)
        return 1 if position < 0 else text.count("\n", 0, position) + 1

    def _append_json_references(
        self,
        path: Path,
        raw: str,
        stats: JsonRewriteStats,
        *,
        own_asset: bool,
        old_name: str,
        new_name: str,
        asset_type: str,
        old_path: str,
        new_path: str,
    ) -> None:
        if path.suffix == ".yyp":
            name_type = "project_resource_name"
            path_type = "project_resource_path"
        elif path.suffix == ".resource_order":
            name_type = path_type = "resource_order"
        elif own_asset and asset_type == "sprite":
            name_type = "sprite_sequence_name"
            path_type = "sprite_keyframe_path"
        elif own_asset:
            name_type = path_type = "asset_internal_json"
        else:
            name_type = path_type = "json_resource_reference"

        for _ in range(stats.names):
            self.references.append(
                AssetReference(
                    file_path=path,
                    line_number=self._line_for(raw, old_name),
                    old_text=old_name,
                    new_text=new_name,
                    reference_type=name_type,
                    context="Structured GameMaker resource name",
                )
            )
        for _ in range(stats.paths):
            self.references.append(
                AssetReference(
                    file_path=path,
                    line_number=self._line_for(raw, old_path),
                    old_text=old_path,
                    new_text=new_path,
                    reference_type=path_type,
                    context="Structured GameMaker resource path",
                )
            )
        for _ in range(stats.expressions):
            self.references.append(
                AssetReference(
                    file_path=path,
                    line_number=self._line_for(raw, old_name),
                    old_text=old_name,
                    new_text=new_name,
                    reference_type="json_gml_expression",
                    context="GameMaker property expression",
                )
            )
        for _ in range(stats.collision_events):
            self.references.append(
                AssetReference(
                    file_path=path,
                    line_number=self._line_for(raw, f"Collision_{old_name}"),
                    old_text=f"Collision_{old_name}",
                    new_text=f"Collision_{new_name}",
                    reference_type="collision_event_identity",
                    context="Collision event metadata and filename",
                )
            )

    def find_all_asset_references(
        self,
        old_name: str,
        new_name: str,
        asset_type: str,
        *,
        old_path: str,
        new_path: str,
    ) -> List[AssetReference]:
        """Find structured JSON references and executable GML identifier uses.

        ``old_path``/``new_path`` are the asset's registered ``.yy`` paths
        before and after the rename. Every scanned file must parse/decode;
        a file that cannot be read fails the scan instead of being skipped.
        """

        self.references.clear()
        self._old_name = old_name
        self._new_name = new_name
        self._asset_type = asset_type
        self._old_path = old_path.replace("\\", "/")
        self._new_path = new_path.replace("\\", "/")
        self._collision_file_renames.clear()

        for path in self._scanned_json_files():
            parsed = load_project_json(path)
            own_asset = self._is_own_asset_file(path, old_path, new_path)
            if asset_type == "object" and path.suffix == ".yy":
                self._collision_file_renames.extend(
                    pair
                    for pair in plan_collision_file_renames(
                        path, parsed, old_name, new_name, old_path=old_path, new_path=new_path
                    )
                    if pair not in self._collision_file_renames
                )
            planned = copy.deepcopy(parsed)
            stats = rewrite_json_asset_references(
                planned,
                old_name,
                new_name,
                asset_type,
                old_path=old_path,
                new_path=new_path,
                own_asset=own_asset,
            )
            if stats.total:
                raw = _read_text_preserving_newlines(path)
                self._append_json_references(
                    path,
                    raw,
                    stats,
                    own_asset=own_asset,
                    old_name=old_name,
                    new_name=new_name,
                    asset_type=asset_type,
                    old_path=self._old_path,
                    new_path=self._new_path,
                )

        for path in self._scanned_gml_files():
            source = read_gml_source(path)
            source_lines = source.splitlines()
            relative = path.relative_to(self.project_root)
            root_kind = relative.parts[0] if relative.parts else "gml"
            reference_type = (
                f"event_{asset_type}_reference"
                if root_kind == "objects"
                else f"script_{asset_type}_reference"
                if root_kind == "scripts"
                else "gml_asset_reference"
            )
            for start, _end, _token in iter_gml_asset_reference_spans(source, old_name):
                line_number = source.count("\n", 0, start) + 1
                line = source_lines[line_number - 1] if source_lines else ""
                rewritten_line, _ = rewrite_gml_asset_identifiers(line, {old_name: new_name})
                self.references.append(
                    AssetReference(
                        file_path=path,
                        line_number=line_number,
                        old_text=line,
                        new_text=rewritten_line,
                        reference_type=reference_type,
                        context="Executable GML identifier",
                    )
                )

        return list(self.references)

    def update_all_references(self, references: List[AssetReference]) -> Tuple[int, int]:
        """Apply all planned changes using atomic per-file replacements."""

        if (
            self._old_name is None
            or self._new_name is None
            or self._asset_type is None
            or self._old_path is None
            or self._new_path is None
        ):
            raise ValueError("find_all_asset_references must be called before update_all_references")

        files_updated = 0
        total_updates = 0
        for path in sorted({reference.file_path for reference in references}):
            if path.suffix == ".gml":
                source = read_gml_source(path)
                rewritten, count = rewrite_gml_asset_identifiers(source, {self._old_name: self._new_name})
                if count:
                    atomic_write_text(path, rewritten)
                    files_updated += 1
                    total_updates += count
                continue

            parsed = load_project_json(path)
            own_asset = self._is_own_asset_file(path, self._old_path, self._new_path)
            stats = rewrite_json_asset_references(
                parsed,
                self._old_name,
                self._new_name,
                self._asset_type,
                old_path=self._old_path,
                new_path=self._new_path,
                own_asset=own_asset,
            )
            if stats.total:
                save_pretty_json_gm(path, parsed)
                files_updated += 1
                total_updates += stats.total

        for source, destination in self._collision_file_renames:
            if not source.is_file():
                raise ValidationError(f"Collision event file disappeared before rename: {source}")
            if destination.exists() and destination != source:
                raise ValidationError(f"Collision event rename destination already exists: {destination}")
            transactional_rename(source, destination)
            files_updated += 1
            total_updates += 1

        return files_updated, total_updates

    def validate_no_stale_references(self, old_name: str) -> List[str]:
        """Return executable or structured references still using ``old_name``."""

        stale: List[str] = []
        for path in self._scanned_gml_files():
            source = read_gml_source(path)
            for start, _end, _token in iter_gml_asset_reference_spans(source, old_name):
                stale.append(f"{path.relative_to(self.project_root).as_posix()}:{source.count(chr(10), 0, start) + 1}")
            if path.name == f"Collision_{old_name}.gml":
                stale.append(f"{path.relative_to(self.project_root).as_posix()}:stale-collision-filename")

        if self._new_name is None or self._asset_type is None or self._old_path is None or self._new_path is None:
            return stale

        for path in self._scanned_json_files():
            parsed = load_project_json(path)
            own_asset = self._is_own_asset_file(path, self._old_path, self._new_path)
            planned = copy.deepcopy(parsed)
            stats = rewrite_json_asset_references(
                planned,
                old_name,
                self._new_name,
                self._asset_type,
                old_path=self._old_path,
                new_path=self._new_path,
                own_asset=own_asset,
            )
            if stats.total:
                stale.append(f"{path.relative_to(self.project_root).as_posix()}:structured-reference")

        return stale


def preflight_asset_rename(
    project_root: Path,
    old_name: str,
    new_name: str,
    asset_type: str,
    *,
    old_path: str,
    new_path: str,
) -> None:
    """Reject unreadable files, collision and GML binding ambiguities before any asset path moves."""
    scanner = ReferenceScanner(project_root)
    for json_path in scanner._scanned_json_files():
        parsed = load_project_json(json_path)
        if asset_type == "object" and json_path.suffix == ".yy" and isinstance(parsed, dict):
            plan_collision_file_renames(json_path, parsed, old_name, new_name, old_path=old_path, new_path=new_path)

    own_script = (scanner.project_root / old_path).parent / f"{old_name}.gml"
    for gml_path in scanner._scanned_gml_files():
        source = read_gml_source(gml_path)
        findings = find_gml_ambiguous_asset_bindings(source, old_name)
        if asset_type == "script" and gml_path == own_script:
            findings = [finding for finding in findings if finding[1] != "function declaration"]
        if findings:
            line, reason = findings[0]
            relative = gml_path.relative_to(scanner.project_root).as_posix()
            raise ValidationError(
                f"Rename blocked: '{old_name}' is an ambiguous {reason} in {relative}:{line}. "
                "Rename that code symbol first, then retry the asset rename."
            )


def comprehensive_rename_asset(
    project_root: Path,
    old_name: str,
    new_name: str,
    asset_type: str,
    *,
    old_path: str,
    new_path: str,
) -> bool:
    """Rewrite and verify token-aware references to a renamed asset."""

    scanner = ReferenceScanner(project_root)
    print(f"[SCAN] Scanning token-aware references to {old_name}...")
    references = scanner.find_all_asset_references(old_name, new_name, asset_type, old_path=old_path, new_path=new_path)
    if references:
        files_updated, total_updates = scanner.update_all_references(references)
        print(f"[OK] Updated {total_updates} token-aware references in {files_updated} files")
    else:
        print("[INFO] No additional token-aware references found")

    stale = scanner.validate_no_stale_references(old_name)
    if stale:
        print(f"[WARN] {len(stale)} executable or structured stale reference(s) remain")
        for reference in stale[:5]:
            print(f"   {reference}")
        return False
    print("[OK] No executable or structured stale references remain")
    return True
