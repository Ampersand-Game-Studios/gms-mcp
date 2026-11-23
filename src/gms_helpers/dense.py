"""Compact, lossless encodings for lists that tool results return.

Agents read every character of a tool result. These helpers write the same information in fewer
characters without dropping any of it: a run of numbered file names becomes one brace range (the
shell's own notation, so it expands with ``echo``), and a line repeated back to back is written
once with its count.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from itertools import groupby

_NUMBERED = re.compile(r"^(.*?)(\d+)(\D*)$")


def _plain(digits: str) -> bool:
    """A number written without leading zeros, so a range of it may change width."""
    return digits == "0" or not digits.startswith("0")


def natural_key(name: str) -> tuple[str, str, int, str]:
    """Order names by their text around the last number, then by that number's value."""
    match = _NUMBERED.match(name)
    if not match:
        return (name, "", -1, name)
    prefix, digits, suffix = match.groups()
    return (prefix, suffix, int(digits), name)


def name_ranges(names: Iterable[str], *, min_run: int = 3) -> list[str]:
    """Sort names and write each run of consecutive numbers as ``prefix{first..last}suffix``.

    ``shot_f00000.png`` … ``shot_f04755.png`` becomes ``shot_f{00000..04755}.png``: every number from
    the first to the last, written with as many digits as the ends are (zsh and bash 4 expand it so;
    macOS's bash 3.2 drops the leading zeros). Only runs whose numbers all have the same width, or
    none of which has a leading zero, are joined. Every other name is listed as is.
    """
    ordered = sorted(set(names), key=natural_key)
    out: list[str] = []
    index = 0
    while index < len(ordered):
        match = _NUMBERED.match(ordered[index])
        end = index
        if match:
            prefix, digits, suffix = match.groups()
            number, width, plain = int(digits), len(digits), _plain(digits)
            while end + 1 < len(ordered):
                following = _NUMBERED.match(ordered[end + 1])
                if not following or following.group(1) != prefix or following.group(3) != suffix:
                    break
                next_digits = following.group(2)
                same_form = len(next_digits) == width if not plain else _plain(next_digits)
                if not same_form or int(next_digits) != number + (end + 1 - index):
                    break
                end += 1
            if end - index + 1 >= min_run:
                last = _NUMBERED.match(ordered[end])
                assert last is not None
                out.append(f"{prefix}{{{digits}..{last.group(2)}}}{suffix}")
                index = end + 1
                continue
        out.append(ordered[index])
        index += 1
    return out


def repeat_counts(lines: Iterable[str]) -> list[str]:
    """Write a line repeated back to back once, followed by `` [×N]``."""
    out: list[str] = []
    for line, group in groupby(lines):
        count = sum(1 for _ in group)
        out.append(line if count == 1 else f"{line} [×{count}]")
    return out


def asset_folders(paths: Iterable[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Group asset files named the GameMaker way, ``<folder>/<name>/<name>.yy``, as ``{folder: [name]}``.

    Returns the groups and, separately, every path that does not follow that form, so that nothing
    is lost: each grouped name expands back to exactly one of the original paths.
    """
    groups: dict[str, list[str]] = {}
    other: list[str] = []
    for path in paths:
        parts = path.split("/")
        if len(parts) >= 3 and parts[-1] == f"{parts[-2]}.yy":
            groups.setdefault("/".join(parts[:-2]), []).append(parts[-2])
        else:
            other.append(path)
    return groups, other


def by_folder(paths: Iterable[str]) -> dict[str, list[str]]:
    """Group paths by their folder, ``{"datafiles/data/act": ["_meta.json", ...]}``; a path with no
    folder is listed under ``""``. Numbered runs of names are written as ranges (see name_ranges)."""
    folders: dict[str, list[str]] = {}
    for path in paths:
        folder, _, name = path.rpartition("/")
        folders.setdefault(folder, []).append(name)
    return {folder: name_ranges(names) for folder, names in folders.items()}


def assets_by_settings(rows: Iterable[dict], settings: Callable[[dict], dict]) -> list[dict]:
    """List asset rows that share the same settings once, with every asset that has them.

    Each row needs a ``path``. An entry is the settings, then ``assets`` (``{folder: [name]}``, see
    asset_folders) and, for paths not named the GameMaker way, ``files``.
    """
    groups: dict[str, tuple[dict, list[str]]] = {}
    for row in rows:
        values = settings(row)
        key = json.dumps(values, sort_keys=True, default=str)
        groups.setdefault(key, (values, []))[1].append(str(row["path"]))
    out: list[dict] = []
    for values, paths in groups.values():
        assets, other = asset_folders(paths)
        entry = dict(values)
        if assets:
            entry["assets"] = {folder: name_ranges(names) for folder, names in assets.items()}
        if other:
            entry["files"] = other
        out.append(entry)
    return out


def shared_fields(records: list[dict], *, keep: tuple[str, ...] = ("name",)) -> tuple[dict, list[dict]]:
    """Split records into the field values most of them share and, per record, only what differs.

    A field is shared when more than half the records have the same value for it. Each record keeps
    the ``keep`` fields, every field whose value differs from the shared one, and lists under
    ``"unset"`` any shared field it does not have at all, so each record can be rebuilt exactly.
    """
    if len(records) < 2:
        return {}, records
    counts: dict[str, dict[str, int]] = {}
    for record in records:
        for key, value in record.items():
            if key in keep:
                continue
            text = json.dumps(value, sort_keys=True, default=str)
            counts.setdefault(key, {})[text] = counts.setdefault(key, {}).get(text, 0) + 1
    shared: dict = {}
    for key, values in counts.items():
        text, count = max(values.items(), key=lambda item: item[1])
        if count * 2 > len(records):
            shared[key] = json.loads(text)
    rows: list[dict] = []
    for record in records:
        row = {
            key: value
            for key, value in record.items()
            if key in keep
            or key not in shared
            or json.dumps(value, sort_keys=True, default=str) != json.dumps(shared[key], sort_keys=True, default=str)
        }
        missing = [key for key in shared if key not in record]
        if missing:
            row["unset"] = missing
        rows.append(row)
    return shared, rows
