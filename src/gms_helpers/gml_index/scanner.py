"""GML file scanner for extracting symbols and references."""

import re
from pathlib import Path
from typing import List, Tuple, Optional

from .symbols import Symbol, SymbolKind, SymbolLocation, SymbolReference


class GMLScanner:
    """Scans GML files to extract symbol definitions and references."""

    # Regex patterns for symbol detection
    PATTERNS = {
        # function name(args) { or function name(args) constructor {
        "function": re.compile(r"^\s*function\s+(\w+)\s*\(", re.MULTILINE),
        # enum EnumName { VALUE1, VALUE2 }
        "enum": re.compile(r"^\s*enum\s+(\w+)\s*\{([^}]*)\}", re.MULTILINE | re.DOTALL),
        # #macro NAME value
        "macro": re.compile(r"^\s*#macro\s+(\w+)\s+(.+?)$", re.MULTILINE),
        # globalvar name;
        "globalvar": re.compile(r"^\s*globalvar\s+(\w+)\s*;", re.MULTILINE),
    }

    # Pattern for identifying word tokens (potential references)
    WORD_PATTERN = re.compile(r"\b([a-zA-Z_]\w*)\b")

    # Built-in GML functions and constants to exclude from references
    # This is a minimal set - could be expanded
    BUILTINS = {
        "if",
        "else",
        "while",
        "for",
        "do",
        "until",
        "repeat",
        "switch",
        "case",
        "default",
        "break",
        "continue",
        "return",
        "exit",
        "with",
        "var",
        "globalvar",
        "enum",
        "function",
        "constructor",
        "new",
        "true",
        "false",
        "undefined",
        "noone",
        "all",
        "self",
        "other",
        "global",
        "local",
        "static",
        "try",
        "catch",
        "finally",
        "throw",
        "and",
        "or",
        "not",
        "xor",
        "mod",
        "div",
    }

    def __init__(self):
        self.symbols: List[Symbol] = []
        self.references: List[SymbolReference] = []

    @staticmethod
    def mask_comments_and_strings(content: str) -> str:
        """Blank out comments and string literals, keeping every offset and newline.

        Each masked character becomes a space (newlines are kept), so match
        positions and line numbers in the masked text equal those in the source.
        String quotes are kept so literals still read as empty strings.
        Handles ``//`` and ``/* */`` comments, "..." strings with escapes,
        GML verbatim strings (@"..." / @'...') and multi-line template strings
        ($"...") without interpolation analysis.
        """
        out = list(content)
        i = 0
        n = len(content)

        def blank(start: int, end: int) -> None:
            for k in range(start, end):
                if out[k] != "\n":
                    out[k] = " "

        while i < n:
            ch = content[i]
            nxt = content[i + 1] if i + 1 < n else ""
            if ch == "/" and nxt == "/":
                end = content.find("\n", i)
                end = n if end == -1 else end
                blank(i, end)
                i = end
            elif ch == "/" and nxt == "*":
                end = content.find("*/", i + 2)
                end = n if end == -1 else end + 2
                blank(i, end)
                i = end
            elif ch == "@" and nxt in ("'", '"'):
                quote = nxt
                end = content.find(quote, i + 2)
                end = n if end == -1 else end
                blank(i + 2, end)
                i = end + 1
            elif ch in ("'", '"'):
                j = i + 1
                while j < n and content[j] != ch and content[j] != "\n":
                    j += 2 if content[j] == "\\" else 1
                end = min(j, n)
                blank(i + 1, end)
                i = end + 1
            else:
                i += 1
        return "".join(out)

    @staticmethod
    def split_parameters(params_str: str, source: Optional[str] = None) -> List[str]:
        """Split a parameter list on top-level commas only.

        ``params_str`` should be masked text (see ``mask_comments_and_strings``);
        pieces are cut from ``source`` (the unmasked text at the same offsets) when
        given. Default values may contain calls, arrays, structs or strings
        (``a = max(1, 2), b = "x,y"``); only top-level commas separate parameters.
        """
        source = params_str if source is None else source
        params: List[str] = []
        depth = 0
        start = 0
        for index, ch in enumerate(params_str):
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
            elif ch == "," and depth == 0:
                params.append(source[start:index].strip())
                start = index + 1
        params.append(source[start:].strip())
        return [p for p in params if p]

    @staticmethod
    def _balanced_close(text: str, open_index: int) -> int:
        """Return the index of the bracket closing ``text[open_index]``, or -1."""
        pairs = {"(": ")", "[": "]", "{": "}"}
        stack = [pairs[text[open_index]]]
        for index in range(open_index + 1, len(text)):
            ch = text[index]
            if ch in pairs:
                stack.append(pairs[ch])
            elif stack and ch == stack[-1]:
                stack.pop()
                if not stack:
                    return index
        return -1

    def scan_content(self, content: str, file_path: Path) -> Tuple[List[Symbol], List[SymbolReference]]:
        """Scan provided GML content for symbols and references."""
        self.symbols = []
        self.references = []

        lines = content.split("\n")
        # Symbol and reference scans run on masked text so comments and strings
        # cannot produce symbols; offsets stay aligned with ``content``.
        masked = self.mask_comments_and_strings(content)

        # Extract doc comments for functions (from the real text)
        doc_comments = self._extract_doc_comments(lines)

        # Find function definitions
        self._scan_functions(masked, file_path, doc_comments, content)

        # Find enum definitions
        self._scan_enums(masked, file_path)

        # Find macro definitions
        self._scan_macros(masked, file_path)

        # Find globalvar declarations
        self._scan_globalvars(masked, file_path)

        # Find references (word tokens that could be symbol usages)
        self._scan_references(masked, file_path, lines)

        return self.symbols, self.references

    def scan_file(self, file_path: Path) -> Tuple[List[Symbol], List[SymbolReference]]:
        """Scan a single GML file for symbols and references.

        Args:
            file_path: Path to the GML file

        Returns:
            Tuple of (symbols found, references found)
        """
        self.symbols = []
        self.references = []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return [], []

        return self.scan_content(content, file_path)

    def _extract_doc_comments(self, lines: List[str]) -> dict:
        """Extract JSDoc-style comments that precede functions.

        Returns dict mapping line number -> doc comment text
        """
        doc_comments = {}
        current_doc = []
        in_doc = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            if stripped.startswith("///") or stripped.startswith("/**"):
                in_doc = True
                current_doc.append(stripped.lstrip("/*").strip())
            elif in_doc and (stripped.startswith("*") or stripped.startswith("//")):
                current_doc.append(stripped.lstrip("*/").strip())
            elif in_doc:
                if current_doc:
                    # Store doc comment for the next non-empty line
                    doc_comments[i] = "\n".join(current_doc)
                current_doc = []
                in_doc = False

        return doc_comments

    def _scan_functions(self, content: str, file_path: Path, doc_comments: dict, source: Optional[str] = None):
        """Scan for function definitions in masked ``content``.

        ``source`` is the unmasked text, used to read default-value literals.
        """
        source = content if source is None else source
        for match in self.PATTERNS["function"].finditer(content):
            name = match.group(1)
            open_index = content.find("(", match.end(1))
            close_index = self._balanced_close(content, open_index) if open_index != -1 else -1
            if close_index == -1:
                continue
            after = content[close_index + 1 :]
            is_constructor = re.match(r"\s*(?::\s*\w+\s*\([^)]*\)\s*)?constructor\b", after) is not None

            # Parse parameters on top-level commas
            params = self.split_parameters(content[open_index + 1 : close_index], source[open_index + 1 : close_index])

            # Calculate line number
            line_num = content[: match.start(1)].count("\n") + 1

            # Check for doc comment
            doc = doc_comments.get(line_num - 1) or doc_comments.get(line_num)

            kind = SymbolKind.CONSTRUCTOR if is_constructor else SymbolKind.FUNCTION

            symbol = Symbol(
                name=name,
                kind=kind,
                location=SymbolLocation(
                    file_path=file_path,
                    line=line_num,
                    column=content.rfind("function", 0, match.start(1)) - content.rfind("\n", 0, match.start(1)),
                ),
                doc_comment=doc,
                parameters=params,
            )
            self.symbols.append(symbol)

    def _scan_enums(self, content: str, file_path: Path):
        """Scan for enum definitions and their values."""
        for match in self.PATTERNS["enum"].finditer(content):
            enum_name = match.group(1)
            enum_body = match.group(2)

            line_num = content[: match.start(1)].count("\n") + 1

            # Add the enum itself
            self.symbols.append(
                Symbol(
                    name=enum_name, kind=SymbolKind.ENUM, location=SymbolLocation(file_path=file_path, line=line_num)
                )
            )

            # Parse enum values on top-level commas: VALUE, VALUE = 0, VALUE = max(1, 2)
            body_offset = match.start(2)
            offset = 0
            for item in self.split_parameters(enum_body):
                item_index = enum_body.find(item, offset)
                offset = item_index + len(item)
                name_match = re.match(r"([A-Za-z_]\w*)", item)
                if name_match:
                    value_name = name_match.group(1)
                    value_line = content[: body_offset + item_index].count("\n") + 1
                    self.symbols.append(
                        Symbol(
                            name=value_name,
                            kind=SymbolKind.ENUM_VALUE,
                            location=SymbolLocation(file_path=file_path, line=value_line),
                            parent_enum=enum_name,
                        )
                    )

    def _scan_macros(self, content: str, file_path: Path):
        """Scan for macro definitions."""
        for match in self.PATTERNS["macro"].finditer(content):
            name = match.group(1)
            line_num = content[: match.start(1)].count("\n") + 1

            self.symbols.append(
                Symbol(name=name, kind=SymbolKind.MACRO, location=SymbolLocation(file_path=file_path, line=line_num))
            )

    def _scan_globalvars(self, content: str, file_path: Path):
        """Scan for globalvar declarations."""
        for match in self.PATTERNS["globalvar"].finditer(content):
            name = match.group(1)
            line_num = content[: match.start(1)].count("\n") + 1

            self.symbols.append(
                Symbol(
                    name=name, kind=SymbolKind.GLOBALVAR, location=SymbolLocation(file_path=file_path, line=line_num)
                )
            )

    def _scan_references(self, content: str, file_path: Path, lines: List[str]):
        """Scan masked ``content`` for potential symbol references (context from ``lines``)."""
        # Get names of symbols defined in this file to help with filtering
        defined_here = {s.name for s in self.symbols}

        for line_num, clean_line in enumerate(content.split("\n"), start=1):
            line = lines[line_num - 1] if line_num - 1 < len(lines) else clean_line
            for match in self.WORD_PATTERN.finditer(clean_line):
                word = match.group(1)

                # Skip builtins and very short names
                if word in self.BUILTINS or len(word) < 2:
                    continue

                # Skip if it looks like a local variable (lowercase start, short)
                # This is a heuristic - not perfect
                if word[0].islower() and len(word) < 4 and word not in defined_here:
                    continue

                self.references.append(
                    SymbolReference(
                        symbol_name=word,
                        location=SymbolLocation(file_path=file_path, line=line_num, column=match.start()),
                        context=line.strip()[:100],  # First 100 chars for context
                    )
                )
