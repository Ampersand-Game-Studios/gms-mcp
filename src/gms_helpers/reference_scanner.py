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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Tuple

from .event_model import rewrite_collision_event_target
from .exceptions import GMSError, ValidationError
from .transactions import transactional_rename
from .utils import atomic_write_text, load_json_loose, save_pretty_json_gm


_IGNORED_DIRECTORIES = {
    ".git",
    ".gms_mcp",
    ".gms-mcp",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}

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


def iter_gml_identifier_spans(source: str) -> Iterator[Tuple[int, int, str]]:
    """Yield executable GML identifier spans, excluding comments and strings.

    The scanner deliberately preserves the source byte-for-byte outside the
    returned spans. It understands line comments, block comments, quoted
    strings, escapes, and GameMaker verbatim strings (the quote after ``@`` is
    still treated as a string delimiter).
    """

    index = 0
    length = len(source)
    while index < length:
        char = source[index]

        if char == "/" and index + 1 < length and source[index + 1] == "/":
            newline = source.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue

        if char == "/" and index + 1 < length and source[index + 1] == "*":
            end = source.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue

        if char in {'"', "'"}:
            quote = char
            verbatim = index > 0 and source[index - 1] == "@"
            index += 1
            while index < length:
                if source[index] == quote:
                    if verbatim and index + 1 < length and source[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                if not verbatim and source[index] == "\\" and index + 1 < length:
                    index += 2
                    continue
                index += 1
            continue

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
    index = 0
    length = len(source)

    def erase(start: int, end: int) -> None:
        for position in range(start, min(end, length)):
            if masked[position] not in {"\n", "\r"}:
                masked[position] = " "

    while index < length:
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            end = length if end < 0 else end
            erase(index, end)
            index = end
            continue
        if source.startswith("/*", index):
            closing = source.find("*/", index + 2)
            end = length if closing < 0 else closing + 2
            erase(index, end)
            index = end
            continue
        if source[index] in {'"', "'"}:
            quote = source[index]
            verbatim = index > 0 and source[index - 1] == "@"
            start = index
            index += 1
            while index < length:
                if source[index] == quote:
                    if verbatim and index + 1 < length and source[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                if not verbatim and source[index] == "\\" and index + 1 < length:
                    index += 2
                else:
                    index += 1
            erase(start, index)
            continue
        index += 1
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
    index = 0
    while index < len(source):
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            closing = source.find("*/", index + 2)
            index = len(source) if closing < 0 else closing + 2
            continue
        if source[index] not in {'"', "'"}:
            index += 1
            continue
        quote = source[index]
        verbatim = index > 0 and source[index - 1] == "@"
        content_start = index + 1
        cursor = content_start
        simple = True
        while cursor < len(source):
            if source[cursor] == quote:
                if verbatim and cursor + 1 < len(source) and source[cursor + 1] == quote:
                    simple = False
                    cursor += 2
                    continue
                if simple:
                    yield content_start, cursor, source[content_start:cursor]
                cursor += 1
                break
            if not verbatim and source[cursor] == "\\" and cursor + 1 < len(source):
                simple = False
                cursor += 2
            else:
                cursor += 1
        index = cursor


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


def count_gml_identifier(source: str, identifier: str) -> int:
    """Count exact bare executable references to a GameMaker asset."""

    return sum(1 for _span in iter_gml_asset_reference_spans(source, identifier))


def _asset_resource_paths(asset_type: str, old_name: str, new_name: str) -> Tuple[str, str, str, str]:
    asset_dir = _ASSET_DIRECTORIES.get(asset_type, f"{asset_type}s")
    if asset_type == "folder":
        return (
            f"folders/{old_name}.yy",
            f"folders/{new_name}.yy",
            "folders/",
            "folders/",
        )
    return (
        f"{asset_dir}/{old_name}/{old_name}.yy",
        f"{asset_dir}/{new_name}/{new_name}.yy",
        f"{asset_dir}/{old_name}/",
        f"{asset_dir}/{new_name}/",
    )


def _rewrite_path_string(
    value: str,
    *,
    old_path: str,
    new_path: str,
    old_directory: str,
    new_directory: str,
    own_asset: bool,
) -> str:
    if value == old_path:
        return new_path
    if value == old_path.replace("/", "\\"):
        return new_path.replace("/", "\\")
    if own_asset and old_directory != new_directory:
        if value.startswith(old_directory):
            return new_directory + value[len(old_directory) :]
        old_windows = old_directory.replace("/", "\\")
        if value.startswith(old_windows):
            return new_directory.replace("/", "\\") + value[len(old_windows) :]
    return value


def count_json_resource_references(data: Any, asset_type: str, asset_name: str) -> int:
    """Count exact structured references to one GameMaker resource path."""

    old_path, _new_path, _old_directory, _new_directory = _asset_resource_paths(
        asset_type,
        asset_name,
        asset_name,
    )
    normalized_target = old_path.replace("\\", "/")
    count = 0

    def visit(node: Any) -> None:
        nonlocal count
        if isinstance(node, str):
            if node.replace("\\", "/") == normalized_target:
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
    own_asset: bool = False,
) -> JsonRewriteStats:
    """Mutate parsed GameMaker JSON using resource-aware rename rules.

    Outside the renamed asset's own ``.yy`` file, a ``name`` is changed only
    when its sibling ``path`` identifies the target resource. Inside the asset,
    exact internal names and resource-directory paths are also updated.
    """

    old_path, new_path, old_directory, new_directory = _asset_resource_paths(asset_type, old_name, new_name)
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

        if asset_type == "object" and rewrite_collision_event_target(node, old_name, new_name):
            stats.collision_events += 1

        original_path = node.get("path")
        target_resource = isinstance(original_path, str) and original_path.replace("\\", "/") == old_path
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


class ReferenceScanner:
    """Discover and apply token-aware references for one GameMaker project."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.references: List[AssetReference] = []
        self._old_name: str | None = None
        self._new_name: str | None = None
        self._asset_type: str | None = None
        self._collision_file_renames: List[Tuple[Path, Path]] = []

    def _is_ignored(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.project_root)
        except ValueError:
            return True
        return any(part in _IGNORED_DIRECTORIES for part in relative.parts)

    def _is_own_asset_file(self, path: Path, old_name: str, new_name: str, asset_type: str) -> bool:
        old_path, new_path, _old_dir, _new_dir = _asset_resource_paths(asset_type, old_name, new_name)
        relative = path.relative_to(self.project_root).as_posix()
        return relative in {old_path, new_path}

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
        old_path, new_path, _old_dir, _new_dir = _asset_resource_paths(asset_type, old_name, new_name)
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

    def _plan_collision_file_renames(
        self,
        object_yy: Path,
        data: Any,
        old_name: str,
        new_name: str,
    ) -> List[Tuple[Path, Path]]:
        planned: List[Tuple[Path, Path]] = []

        def visit(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    visit(item)
                return
            if not isinstance(node, dict):
                return
            candidate = copy.deepcopy(node)
            if rewrite_collision_event_target(candidate, old_name, new_name):
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

    def find_all_asset_references(self, old_name: str, new_name: str, asset_type: str) -> List[AssetReference]:
        """Find structured JSON references and executable GML identifier uses."""

        self.references.clear()
        self._old_name = old_name
        self._new_name = new_name
        self._asset_type = asset_type
        self._collision_file_renames.clear()

        json_files = {
            *self.project_root.rglob("*.yy"),
            *self.project_root.rglob("*.yyp"),
            *self.project_root.rglob("*.resource_order"),
        }
        for path in sorted(json_files):
            if self._is_ignored(path):
                continue
            parsed = load_json_loose(path)
            if parsed is None:
                continue
            own_asset = self._is_own_asset_file(path, old_name, new_name, asset_type)
            if asset_type == "object" and path.suffix == ".yy":
                self._collision_file_renames.extend(
                    pair
                    for pair in self._plan_collision_file_renames(path, parsed, old_name, new_name)
                    if pair not in self._collision_file_renames
                )
            planned = copy.deepcopy(parsed)
            stats = rewrite_json_asset_references(
                planned,
                old_name,
                new_name,
                asset_type,
                own_asset=own_asset,
            )
            if stats.total:
                raw = path.read_text(encoding="utf-8", errors="replace")
                self._append_json_references(
                    path,
                    raw,
                    stats,
                    own_asset=own_asset,
                    old_name=old_name,
                    new_name=new_name,
                    asset_type=asset_type,
                )

        for path in sorted(self.project_root.rglob("*.gml")):
            if self._is_ignored(path):
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
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

        if self._old_name is None or self._new_name is None or self._asset_type is None:
            raise ValueError("find_all_asset_references must be called before update_all_references")

        files_updated = 0
        total_updates = 0
        for path in sorted({reference.file_path for reference in references}):
            if path.suffix == ".gml":
                source = path.read_text(encoding="utf-8")
                rewritten, count = rewrite_gml_asset_identifiers(source, {self._old_name: self._new_name})
                if count:
                    atomic_write_text(path, rewritten)
                    files_updated += 1
                    total_updates += count
                continue

            parsed = load_json_loose(path)
            if parsed is None:
                raise ValueError(f"Could not parse GameMaker JSON: {path}")
            own_asset = self._is_own_asset_file(path, self._old_name, self._new_name, self._asset_type)
            stats = rewrite_json_asset_references(
                parsed,
                self._old_name,
                self._new_name,
                self._asset_type,
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
        for path in sorted(self.project_root.rglob("*.gml")):
            if self._is_ignored(path):
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            for start, _end, _token in iter_gml_asset_reference_spans(source, old_name):
                stale.append(f"{path.relative_to(self.project_root).as_posix()}:{source.count(chr(10), 0, start) + 1}")
            if path.name == f"Collision_{old_name}.gml":
                stale.append(f"{path.relative_to(self.project_root).as_posix()}:stale-collision-filename")

        if self._new_name is None or self._asset_type is None:
            return stale

        json_files = {
            *self.project_root.rglob("*.yy"),
            *self.project_root.rglob("*.yyp"),
            *self.project_root.rglob("*.resource_order"),
        }
        for path in sorted(json_files):
            if self._is_ignored(path):
                continue
            parsed = load_json_loose(path)
            if parsed is None:
                continue
            own_asset = self._is_own_asset_file(path, old_name, self._new_name, self._asset_type)
            planned = copy.deepcopy(parsed)
            stats = rewrite_json_asset_references(
                planned,
                old_name,
                self._new_name,
                self._asset_type,
                own_asset=own_asset,
            )
            if stats.total:
                stale.append(f"{path.relative_to(self.project_root).as_posix()}:structured-reference")

        return stale


def preflight_asset_rename(project_root: Path, old_name: str, new_name: str, asset_type: str) -> None:
    """Reject collision and GML binding ambiguities before any asset path moves."""
    scanner = ReferenceScanner(project_root)
    if asset_type == "object":
        for object_yy in sorted((scanner.project_root / "objects").glob("*/*.yy")):
            parsed = load_json_loose(object_yy)
            if isinstance(parsed, dict):
                scanner._plan_collision_file_renames(object_yy, parsed, old_name, new_name)

    own_script = scanner.project_root / "scripts" / old_name / f"{old_name}.gml"
    for gml_path in sorted(scanner.project_root.rglob("*.gml")):
        if scanner._is_ignored(gml_path):
            continue
        source = gml_path.read_text(encoding="utf-8", errors="replace")
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


def comprehensive_rename_asset(project_root: Path, old_name: str, new_name: str, asset_type: str) -> bool:
    """Rewrite and verify token-aware references to a renamed asset."""

    scanner = ReferenceScanner(project_root)
    print(f"[SCAN] Scanning token-aware references to {old_name}...")
    references = scanner.find_all_asset_references(old_name, new_name, asset_type)
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


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python reference_scanner.py <project_root> <old_name> <new_name> <asset_type>")
        sys.exit(1)

    try:
        success = comprehensive_rename_asset(Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4])
        sys.exit(0 if success else 1)
    except GMSError as exc:
        print(f"[ERROR] {exc.message}")
        sys.exit(exc.exit_code)
    except Exception as exc:
        print(f"[ERROR] Unexpected error: {exc}")
        sys.exit(1)
