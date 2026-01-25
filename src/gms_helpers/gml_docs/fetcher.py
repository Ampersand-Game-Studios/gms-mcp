"""
Fetcher for GML documentation from manual.gamemaker.io.

Handles HTTP requests and basic HTML parsing.
"""

from __future__ import annotations

import re
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from .cache import CachedDoc, DocCache, FunctionIndexEntry

BASE_URL = "https://manual.gamemaker.io/monthly/en/"
GML_REFERENCE_URL = BASE_URL + "GameMaker_Language/GML_Reference/GML_Reference.htm"

# Rate limiting: minimum seconds between requests
MIN_REQUEST_INTERVAL = 0.5
_last_request_time = 0.0


class SimpleHTMLTextExtractor(HTMLParser):
    """Extract text content from HTML."""

    def __init__(self):
        super().__init__()
        self.text_parts: List[str] = []
        self._in_script = False
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag == "script":
            self._in_script = True
        elif tag == "style":
            self._in_style = True
        elif tag == "br":
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False
        elif tag == "style":
            self._in_style = False
        elif tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._in_script and not self._in_style:
            self.text_parts.append(data)

    def get_text(self) -> str:
        return "".join(self.text_parts)


class GMLDocParser(HTMLParser):
    """Parse GML function documentation pages."""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.description_parts: List[str] = []
        self.syntax = ""
        self.parameters: List[Dict[str, str]] = []
        self.returns = ""
        self.examples: List[str] = []

        # Parsing state
        self._in_title = False
        self._in_body = False
        self._in_code = False
        self._in_pre = False
        self._in_table = False
        self._in_thead = False
        self._in_td = False
        self._in_th = False
        self._current_section = ""
        self._current_row: List[str] = []
        self._buffer: List[str] = []
        self._all_text: List[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = dict(attrs)

        if tag == "title":
            self._in_title = True
        elif tag == "body":
            self._in_body = True
        elif tag == "pre":
            self._in_pre = True
            self._buffer = []
        elif tag == "code":
            self._in_code = True
            if not self._in_pre:
                self._buffer = []
        elif tag == "table":
            self._in_table = True
        elif tag == "thead":
            self._in_thead = True
        elif tag == "tr":
            self._current_row = []
        elif tag == "td":
            self._in_td = True
            self._buffer = []
        elif tag == "th":
            self._in_th = True
            self._buffer = []
        elif tag in ("h4", "h3", "h2"):
            self._buffer = []
        elif tag == "p" and self._in_body:
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "body":
            self._in_body = False
        elif tag == "pre":
            self._in_pre = False
            code_text = "".join(self._buffer).strip()
            if code_text:
                if self._current_section == "syntax":
                    self.syntax = code_text
                elif self._current_section == "example":
                    self.examples.append(code_text)
                elif not self.syntax and "(" in code_text and ");" in code_text:
                    # Likely a syntax block - function call with semicolon
                    self.syntax = code_text
        elif tag == "code":
            self._in_code = False
            if not self._in_pre:
                code_text = "".join(self._buffer).strip()
                if code_text:
                    # Check if this looks like syntax (function signature)
                    if self._current_section == "syntax" or (
                        not self.syntax and "(" in code_text and ")" in code_text and len(code_text) < 200
                    ):
                        self.syntax = code_text
        elif tag == "table":
            self._in_table = False
        elif tag == "thead":
            self._in_thead = False
        elif tag == "tr" and self._current_row and not self._in_thead:
            # Process table row - parameters table has 3 columns
            if len(self._current_row) >= 3 and self._current_section == "arguments":
                name = self._current_row[0].strip()
                # Skip header rows
                if name.lower() not in ("argument", "name", "parameter"):
                    self.parameters.append({
                        "name": name,
                        "type": self._current_row[1].strip(),
                        "description": self._current_row[2].strip(),
                    })
        elif tag == "td":
            self._in_td = False
            self._current_row.append("".join(self._buffer).strip())
        elif tag == "th":
            self._in_th = False
            # Check header text to determine section
            header_text = "".join(self._buffer).strip().lower()
            if "argument" in header_text or "parameter" in header_text:
                self._current_section = "arguments"
        elif tag in ("h4", "h3", "h2"):
            header = "".join(self._buffer).strip().lower()
            if "syntax" in header:
                self._current_section = "syntax"
            elif "argument" in header or "parameter" in header:
                self._current_section = "arguments"
            elif "return" in header:
                self._current_section = "returns"
            elif "example" in header:
                self._current_section = "example"
            elif "description" in header:
                self._current_section = ""  # Description is the default
            else:
                # Don't reset section for unknown headers
                pass
        elif tag == "p" and self._in_body and not self._in_table:
            text = "".join(self._buffer).strip()
            if text:
                if self._current_section == "returns":
                    if not self.returns:
                        self.returns = text
                elif self._current_section in ("", "description"):
                    self.description_parts.append(text)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._in_pre or self._in_code or self._in_td or self._in_th:
            self._buffer.append(data)
        elif self._in_body:
            self._buffer.append(data)
            self._all_text.append(data)

    def get_description(self) -> str:
        return "\n\n".join(self.description_parts)

    def post_process(self, function_name: str) -> None:
        """Post-process to extract missing data from raw text."""
        full_text = "".join(self._all_text)

        # Try to extract syntax if not found
        if not self.syntax:
            # Look for function_name followed by parentheses
            pattern = rf'{re.escape(function_name)}\s*\([^)]*\)\s*;?'
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                self.syntax = match.group(0).strip()

        # Try to extract returns if not found
        if not self.returns or self.returns == "N/A":
            returns_pattern = r'Returns?:?\s*([^\n]+)'
            match = re.search(returns_pattern, full_text, re.IGNORECASE)
            if match:
                ret = match.group(1).strip()
                if ret and ret.lower() not in ("", "n/a"):
                    self.returns = ret


class IndexParser(HTMLParser):
    """Parse the GML Reference index page to extract function links."""

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.functions: Dict[str, FunctionIndexEntry] = {}
        self._current_category = ""
        self._current_subcategory = ""
        self._in_link = False
        self._current_href = ""
        self._link_text = ""

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = dict(attrs)

        if tag == "a" and "href" in attrs_dict:
            href = attrs_dict["href"]
            if href and ".htm" in href and not href.startswith("http"):
                self._in_link = True
                self._current_href = href
                self._link_text = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            self._in_link = False
            name = self._link_text.strip()

            # Filter to likely function names (contain letters, may have underscores)
            if name and re.match(r"^[a-z_][a-z0-9_]*$", name, re.IGNORECASE):
                url = urljoin(self.base_url, self._current_href)

                # Extract category from URL path
                parts = self._current_href.replace("\\", "/").split("/")
                category = parts[-2] if len(parts) >= 2 else "General"
                subcategory = parts[-3] if len(parts) >= 3 else ""

                self.functions[name.lower()] = FunctionIndexEntry(
                    name=name,
                    category=category.replace("_", " "),
                    subcategory=subcategory.replace("_", " "),
                    url=url,
                )

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._link_text += data


def _rate_limit() -> None:
    """Enforce rate limiting between requests."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def _fetch_url(url: str, timeout: float = 30.0) -> str:
    """Fetch a URL with rate limiting and error handling."""
    _rate_limit()

    headers = {
        "User-Agent": "gms-mcp/1.0 (GameMaker Documentation Tool)"
    }
    request = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP error {e.code} fetching {url}: {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error fetching {url}: {e.reason}")
    except TimeoutError:
        raise RuntimeError(f"Timeout fetching {url}")


def fetch_function_index(
    cache: Optional[DocCache] = None,
    force_refresh: bool = False,
) -> Dict[str, FunctionIndexEntry]:
    """
    Fetch the function index from the GML Reference.

    Args:
        cache: Optional cache instance to use.
        force_refresh: If True, bypass cache and fetch fresh data.

    Returns:
        Dictionary mapping lowercase function names to FunctionIndexEntry.
    """
    if cache is None:
        cache = DocCache()

    # Check cache first
    if not force_refresh:
        cached = cache.get_index()
        if cached is not None:
            return cached

    all_functions: Dict[str, FunctionIndexEntry] = {}

    # List of category pages to fetch - these contain the actual function lists
    category_pages = [
        ("Drawing", "Sprites_And_Tiles", "Drawing/Sprites_And_Tiles/Sprites_And_Tiles.htm"),
        ("Drawing", "Basic Forms", "Drawing/Basic_Forms/Basic_Forms.htm"),
        ("Drawing", "Text", "Drawing/Text/Text.htm"),
        ("Drawing", "Colour", "Drawing/Colour_And_Alpha/Colour_And_Alpha.htm"),
        ("Drawing", "GPU", "Drawing/GPU_Control/GPU_Control.htm"),
        ("Drawing", "Primitives", "Drawing/Primitives/Primitives.htm"),
        ("Drawing", "Surfaces", "Drawing/Surfaces/Surfaces.htm"),
        ("Drawing", "Particles", "Drawing/Particles/Particles.htm"),
        ("Strings", "", "Strings/Strings.htm"),
        ("Maths", "Number Functions", "Maths_And_Numbers/Number_Functions/Number_Functions.htm"),
        ("Maths", "Angles", "Maths_And_Numbers/Angles_And_Distance/Angles_And_Distance.htm"),
        ("Maths", "Matrix", "Maths_And_Numbers/Matrix_Functions/Matrix_Functions.htm"),
        ("Maths", "Date Time", "Maths_And_Numbers/Date_And_Time/Date_And_Time.htm"),
        ("Asset Management", "Sprites", "Asset_Management/Sprites/Sprites.htm"),
        ("Asset Management", "Audio", "Asset_Management/Audio/Audio.htm"),
        ("Asset Management", "Rooms", "Asset_Management/Rooms/Rooms.htm"),
        ("Asset Management", "Objects", "Asset_Management/Objects/Objects.htm"),
        ("Asset Management", "Instances", "Asset_Management/Instances/Instances.htm"),
        ("Movement", "Collisions", "Movement_And_Collisions/Collisions/Collisions.htm"),
        ("Movement", "Motion Planning", "Movement_And_Collisions/Motion_Planning/Motion_Planning.htm"),
        ("Data Structures", "DS Lists", "Data_Structures/DS_Lists/DS_Lists.htm"),
        ("Data Structures", "DS Maps", "Data_Structures/DS_Maps/DS_Maps.htm"),
        ("Data Structures", "DS Grids", "Data_Structures/DS_Grids/DS_Grids.htm"),
        ("Data Structures", "DS Stacks", "Data_Structures/DS_Stacks/DS_Stacks.htm"),
        ("Data Structures", "DS Queues", "Data_Structures/DS_Queues/DS_Queues.htm"),
        ("Data Structures", "DS Priority", "Data_Structures/DS_Priority_Queues/DS_Priority_Queues.htm"),
        ("Arrays", "", "Variable_Functions/Array_Functions.htm"),
        ("Variable", "", "Variable_Functions/Variable_Functions.htm"),
        ("Game", "Input", "Game_Input/Game_Input.htm"),
        ("Game", "Keyboard", "Game_Input/Keyboard_Input/Keyboard_Input.htm"),
        ("Game", "Mouse", "Game_Input/Mouse_Input/Mouse_Input.htm"),
        ("Game", "Gamepad", "Game_Input/GamePad_Input/Gamepad_Input.htm"),
        ("Cameras", "", "Cameras_And_Display/Cameras_And_Viewports/Cameras_And_Viewports.htm"),
        ("Buffers", "", "Buffers/Buffers.htm"),
        ("File", "Handling", "File_Handling/File_Handling.htm"),
        ("File", "INI", "File_Handling/Ini_Files/Ini_Files.htm"),
        ("File", "Text", "File_Handling/Text_Files/Text_Files.htm"),
        ("File", "Binary", "File_Handling/Binary_Files/Binary_Files.htm"),
        ("File", "JSON", "File_Handling/Encoding_And_Hashing/Encoding_And_Hashing.htm"),
        ("OS", "", "OS_And_Compiler/OS_And_Compiler.htm"),
        ("Debugging", "", "Debugging/Debugging.htm"),
        ("Networking", "", "Networking/Networking.htm"),
        ("Physics", "", "Physics/Physics.htm"),
        ("Time Sources", "", "Time_Sources/Time_Sources.htm"),
        ("Asynchronous", "", "Asynchronous_Functions/Asynchronous_Functions.htm"),
    ]

    for category, subcategory, page_path in category_pages:
        try:
            url = BASE_URL + "GameMaker_Language/GML_Reference/" + page_path
            html = _fetch_url(url)
            parser = IndexParser(url)
            parser.feed(html)

            # Update category info for parsed functions
            for name, entry in parser.functions.items():
                entry.category = category
                if subcategory:
                    entry.subcategory = subcategory
                all_functions[name] = entry

        except Exception:
            # Skip categories that fail
            continue

    # Save to cache
    cache.save_index(all_functions)

    return all_functions


def fetch_function_doc(
    name: str,
    cache: Optional[DocCache] = None,
    force_refresh: bool = False,
) -> Optional[CachedDoc]:
    """
    Fetch documentation for a specific function.

    Args:
        name: The function name to look up.
        cache: Optional cache instance to use.
        force_refresh: If True, bypass cache and fetch fresh data.

    Returns:
        CachedDoc with the function documentation, or None if not found.
    """
    if cache is None:
        cache = DocCache()

    name_lower = name.lower()

    # Check function cache first
    if not force_refresh:
        cached = cache.get_function(name_lower)
        if cached is not None:
            return cached

    # Get the index to find the URL
    index = fetch_function_index(cache, force_refresh=False)

    if name_lower not in index:
        # Try searching for similar names
        return None

    entry = index[name_lower]

    # Fetch the function page
    try:
        html = _fetch_url(entry.url)
    except RuntimeError:
        return None

    # Parse the documentation
    parser = GMLDocParser()
    parser.feed(html)
    parser.post_process(entry.name)

    # Create cached doc
    doc = CachedDoc(
        name=entry.name,
        category=entry.category,
        subcategory=entry.subcategory,
        url=entry.url,
        description=parser.get_description(),
        syntax=parser.syntax,
        parameters=parser.parameters,
        returns=parser.returns or "N/A",
        examples=parser.examples,
        cached_at=time.time(),
    )

    # Save to cache
    cache.save_function(doc)

    return doc
