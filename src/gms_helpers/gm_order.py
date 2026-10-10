"""Ordering of ``.yyp`` registries (resources, folders, included files).

GameMaker LTS 2026 keeps these arrays in the IDE's culture-aware order: punctuation sorts
before digits, digits before letters, letters compare case-insensitively and lowercase
wins ties. Igor's project loader in runtime 2026.0.0.23 is sensitive to that order, so a
new entry must be inserted where the IDE would put it, and existing entries must never be
reshuffled: other tools and other people edit the same file line by line.

Earlier IDEs sorted by resource name. ``detect_ordering`` therefore proves which rule a
project already follows before anything is inserted.
"""

from __future__ import annotations

from bisect import bisect_right
from typing import Any, Callable, Sequence

# Punctuation in the order the 2026 IDE collates it.
_PUNCTUATION = "_-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"

SortKey = Callable[[str], Any]


def _weight(character: str) -> tuple[int, int]:
    if character in _PUNCTUATION:
        return (1, _PUNCTUATION.index(character))
    if character.isdigit():
        return (2, ord(character))
    if character.isalpha():
        return (3, ord(character.lower()))
    return (0, ord(character))


def ide_2026_key(text: str) -> tuple[list[tuple[int, int]], list[int]]:
    """Collation key matching the GameMaker 2026 IDE."""
    return (
        [_weight(character) for character in text],
        [0 if (character.islower() or not character.isalpha()) else 1 for character in text],
    )


def lowercase_key(text: str) -> str:
    return text.lower()


def is_sorted(values: Sequence[str], key: SortKey) -> bool:
    keys = [key(value) for value in values]
    return all(left <= right for left, right in zip(keys, keys[1:]))


def detect_ordering(
    entries: Sequence[Any],
    candidates: Sequence[tuple[str, Callable[[Any], str], SortKey]],
) -> tuple[str, Callable[[Any], str], SortKey] | None:
    """Return the first candidate rule the existing entries already satisfy."""
    for candidate in candidates:
        _label, field, key = candidate
        try:
            if is_sorted([field(entry) for entry in entries], key):
                return candidate
        except (KeyError, TypeError, AttributeError):
            continue
    return None


def insert_ordered(
    entries: list[Any],
    new_entry: Any,
    candidates: Sequence[tuple[str, Callable[[Any], str], SortKey]],
) -> tuple[int, str]:
    """Insert ``new_entry`` where the project's own ordering puts it.

    Existing entries keep their positions. When the array follows none of the known
    rules (it was edited by hand), the entry is placed by the first rule on a best-effort
    basis and the returned label is ``"unordered"``.
    """
    rule = detect_ordering(entries, candidates)
    label, field, key = rule if rule is not None else candidates[0]
    wanted = key(field(new_entry))
    if rule is not None:
        index = bisect_right([key(field(entry)) for entry in entries], wanted)
    else:
        index = len(entries)
        for position, entry in enumerate(entries):
            try:
                if key(field(entry)) > wanted:
                    index = position
                    break
            except (KeyError, TypeError, AttributeError):
                continue
        label = "unordered"
    entries.insert(index, new_entry)
    return index, label


def _resource_path(entry: Any) -> str:
    return str(entry["id"]["path"])


def _resource_name(entry: Any) -> str:
    return str(entry["id"]["name"])


def _folder_path(entry: Any) -> str:
    return str(entry["folderPath"])


def _folder_name(entry: Any) -> str:
    return str(entry.get("name") or entry["folderPath"])


def _included_file(entry: Any) -> str:
    return f"{entry.get('filePath', '')}/{entry.get('name', '')}"


RESOURCE_ORDERINGS = (
    ("ide-2026-path", _resource_path, ide_2026_key),
    ("name-lowercase", _resource_name, lowercase_key),
    ("ide-2026-name", _resource_name, ide_2026_key),
    ("path-lowercase", _resource_path, lowercase_key),
)
FOLDER_ORDERINGS = (
    ("ide-2026-path", _folder_path, ide_2026_key),
    ("name-lowercase", _folder_name, lowercase_key),
    ("path-lowercase", _folder_path, lowercase_key),
)
INCLUDED_FILE_ORDERINGS = (
    ("ide-2026-path", _included_file, ide_2026_key),
    ("path-lowercase", _included_file, lowercase_key),
)
