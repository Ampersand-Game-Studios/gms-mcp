"""
Shared utilities for GameMaker asset management
"""

import json
import re
import sys
import uuid
import struct
import zlib
from pathlib import Path
from typing import Dict, Any, List
import os

from .exceptions import GMSError, ProjectNotFoundError, ValidationError

# ---- make console prints Unicode-safe on Windows -----------------
import sys, os
if os.name == "nt":                      # Windows only
    try:                             # Python 3.7+
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        # Older Pythons - fall back to write-through helper
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                     errors="replace", line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                     errors="replace", line_buffering=True)
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# JSON Utilities
# ------------------------------------------------------------------
TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

def strip_trailing_commas(raw_text: str) -> str:
    """Remove JSON-breaking trailing commas."""
    return TRAILING_COMMA_RE.sub(r"\1", raw_text)

def load_json_loose(path: Path) -> Dict[str, Any] | None:
    """Load a (possibly trailing-comma) JSON file."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
        
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(strip_trailing_commas(raw))
        except json.JSONDecodeError:
            return None

def save_pretty_json(path: Path, data: Dict[str, Any]):
    """Pretty-print JSON (no trailing commas) - for compatibility."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def save_pretty_json_gm(path: Path, data: Dict[str, Any]):
    """Pretty-print JSON with GameMaker-style trailing commas."""
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    json_str = add_trailing_commas(json_str)
    path.write_text(json_str, encoding="utf-8")

def save_json_loose(path: Path | str, data: Dict[str, Any]):
    """Save data as JSON with GameMaker-style trailing commas."""
    if isinstance(path, str):
        path = Path(path)
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    json_str = add_trailing_commas(json_str)
    path.write_text(json_str, encoding="utf-8")

def save_json(data, file_path):
    """Save data as JSON to a file with GameMaker-style trailing commas."""
    dir_path = os.path.dirname(file_path)
    if dir_path:  # Only create directory if there is one
        os.makedirs(dir_path, exist_ok=True)
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    json_str = add_trailing_commas(json_str)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(json_str)

# ------------------------------------------------------------------
# Project Management
# ------------------------------------------------------------------
def find_yyp(project_root: Path) -> Path:
    """Pick the first .yyp file in the project root."""
    yyp_files = list(project_root.glob("*.yyp"))
    if not yyp_files:
        raise ProjectNotFoundError(f"No .yyp file found in project root: {project_root}")
    return yyp_files[0]

def ensure_directory(path: Path):
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)

def verify_parent_path_exists(yyp_data: Dict[str, Any], parent_path: str) -> bool:
    """Check if the parent folder path exists in the project's folder structure."""
    # Empty parent path is considered valid (root level)
    if not parent_path:
        return True
        
    # Check both "Folders" and "folders" keys for compatibility
    folders = yyp_data.get("Folders", []) or yyp_data.get("folders", [])
    for folder in folders:
        if folder.get("folderPath") == parent_path:
            return True
    return False

# ------------------------------------------------------------------
# YYP Management
# ------------------------------------------------------------------
def insert_into_resources(resources: List[Dict], asset_name: str, asset_path: str):
    """Insert a new resource into the resources array in alphabetical order."""
    # Check for duplicates (safely handle malformed entries)
    for r in resources:
        existing_name = r.get("id", {}).get("name") if isinstance(r.get("id"), dict) else None
        if existing_name == asset_name:
            print(f"'{asset_name}' already present in .yyp - skipping insertion")
            return False
    
    # Add new resource
    resources.append({"id": {"name": asset_name, "path": asset_path}})
    
    # Sort alphabetically (case-insensitive), safely handle malformed entries
    def get_sort_key(r):
        if isinstance(r.get("id"), dict) and "name" in r["id"]:
            return r["id"]["name"].lower()
        return ""  # Put malformed entries at the beginning
    
    resources.sort(key=get_sort_key)
    return True

def insert_into_folders(folders: List[Dict], folder_name: str, folder_path: str):
    """Insert a new folder into the Folders array in alphabetical order."""
    # Check for duplicates
    if any(f["folderPath"] == folder_path for f in folders):
        print(f"Folder '{folder_path}' already exists - skipping insertion")
        return False
    
    # Add new folder
    folders.append({
        "$GMFolder": "",
        "%Name": folder_name,
        "folderPath": folder_path,
        "name": folder_name,
        "resourceType": "GMFolder",
        "resourceVersion": "2.0"
    })
    
    # Sort alphabetically by name (fallback to folderPath if name is missing)
    def get_folder_name(f):
        if "name" in f:
            return f["name"].lower()
        # Extract folder name from "folders/FolderName.yy" format
        folder_path = f.get("folderPath", "")
        if "/" in folder_path and folder_path.endswith(".yy"):
            return folder_path.split("/")[-1][:-3].lower()  # Remove .yy extension
        return folder_path.lower()
    
    folders.sort(key=get_folder_name)
    return True

# ------------------------------------------------------------------
# UUID Generation
# ------------------------------------------------------------------
def generate_uuid() -> str:
    """Generate a UUID in the format GameMaker expects (32 hex characters, no dashes)."""
    return str(uuid.uuid4()).replace('-', '')

# ------------------------------------------------------------------
# File Templates
# ------------------------------------------------------------------
def create_dummy_png(file_path, width=64, height=64):
    """Create a dummy PNG file for sprites using basic binary data."""
    path = Path(file_path)
    if path.parent:
        os.makedirs(path.parent, exist_ok=True)

    try:
        width_value = int(width)
        height_value = int(height)
    except (TypeError, ValueError):
        width_value = 1
        height_value = 1
    if width_value <= 0:
        width_value = 1
    if height_value <= 0:
        height_value = 1

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return length + chunk_type + data + struct.pack(">I", crc)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width_value, height_value, 8, 6, 0, 0, 0)
    row = b"\x00" + (b"\x00" * (width_value * 4))
    raw = row * height_value
    compressed = zlib.compress(raw)
    png_data = (
        signature
        + _chunk(b"IHDR", ihdr_data)
        + _chunk(b"IDAT", compressed)
        + _chunk(b"IEND", b"")
    )

    with open(path, "wb") as f:
        f.write(png_data)

def load_json(file_path):
    """Load and parse a JSON file, handling GameMaker's trailing commas."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # GameMaker JSON files often have trailing commas, which Python's json module doesn't like
        # We'll try to parse as-is first, then clean up trailing commas if needed
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to fix trailing commas using the same logic as load_json_loose
            content = strip_trailing_commas(content)
            return json.loads(content)
            
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {file_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {file_path}: {e}")

def add_trailing_commas(json_str):
    """Add trailing commas to JSON string to match GameMaker's style."""
    lines = json_str.split('\n')
    
    # Find the last non-whitespace line index
    last_line_index = len(lines) - 1
    while last_line_index >= 0 and lines[last_line_index].strip() == '':
        last_line_index -= 1
    
    # Add trailing commas to all lines except the last non-whitespace line
    for i in range(len(lines)):
        if i >= last_line_index:
            continue  # Skip the final closing brace/bracket
            
        stripped = lines[i].strip()
        # Skip empty lines, opening braces/brackets, and lines ending with opening braces/brackets
        if (not stripped or 
            stripped in ['{', '['] or 
            stripped.endswith('{') or 
            stripped.endswith('[')):
            continue
            
        # Add comma to any line that doesn't already have one
        if not stripped.endswith(','):
            # Add comma while preserving indentation
            indent = len(lines[i]) - len(lines[i].lstrip())
            lines[i] = ' ' * indent + stripped + ','
    
    return '\n'.join(lines)

def validate_name(name, asset_type, allow_constructor=False, config=None):
    """Validate asset name follows configurable naming conventions.
    
    Args:
        name: The asset name to validate
        asset_type: The type of asset (e.g., 'object', 'sprite', 'script')
        allow_constructor: If True, allow PascalCase for constructor scripts
        config: Optional NamingConfig instance. If None, uses cached config.
        
    Raises:
        ValueError: If the name doesn't match the configured pattern
    """
    # Handle None input
    if name is None:
        raise ValueError("Asset name cannot be None")
    
    # Get config (uses caching)
    if config is None:
        from .naming_config import get_config
        config = get_config()
    
    # Check if naming validation is enabled
    if not config.naming_enabled:
        return  # Skip all validation
    
    # Get the rule for this asset type
    rule = config.get_rule(asset_type)
    if not rule:
        return  # No rule defined for this type, skip validation
    
    # Handle constructor scripts specially
    if asset_type == 'script' and allow_constructor:
        if config.allows_pascal_constructors('script'):
            if re.match(r'^[A-Z][a-zA-Z0-9]*$', name):
                return  # Valid PascalCase constructor name
    
    # Get the pattern for validation
    pattern = rule.get("pattern")
    if not pattern:
        return  # No pattern defined, skip validation
    
    # Validate against the pattern
    if not re.match(pattern, name):
        # Build a helpful error message
        prefix = rule.get("prefix", "")
        description = rule.get("description", "")
        
        if isinstance(prefix, list):
            prefix_str = " or ".join(f"'{p}'" for p in prefix)
        elif prefix:
            prefix_str = f"'{prefix}'"
        else:
            prefix_str = ""
        
        # Use description if available, otherwise build message from prefix
        if description:
            raise ValueError(f"{asset_type.capitalize()} name '{name}' invalid: {description}")
        elif prefix_str:
            raise ValueError(f"{asset_type.capitalize()} name '{name}' must start with {prefix_str} prefix")
        else:
            raise ValueError(f"{asset_type.capitalize()} name '{name}' does not match expected naming pattern")

def validate_working_directory():
    """
    Validate that we're in a GameMaker project directory with helpful error messages.
    Returns the .yyp filename if valid, exits with error message if not.
    """
    import sys
    import os
    
    # Check for .yyp files in current directory
    yyp_files = [f for f in os.listdir('.') if f.endswith('.yyp')]
    
    if not yyp_files:
        message = (
            "ERROR: No .yyp file found in current directory\n"
            f"Current directory: {os.getcwd()}\n\n"
            "SOLUTION:\n"
            "   - cd into the directory that contains your .yyp file, OR\n"
            "   - run with: gms --project-root <path-to-gamemaker-project>, OR\n"
            "   - set env var: GM_PROJECT_ROOT or PROJECT_ROOT=<absolute path to gamemaker project>\n\n"
            "EXPLANATION: CLI tools require direct access to the GameMaker project file (.yyp)."
        )
        raise ProjectNotFoundError(message)
    
    if len(yyp_files) > 1:
        print("[WARN]  WARNING: Multiple .yyp files found in current directory:")
        for f in yyp_files:
            print(f"   - {f}")
        print(f"   Using: {yyp_files[0]}")
        print()
    
    print(f"[OK] Found GameMaker project: {yyp_files[0]}")
    return yyp_files[0]


def _list_yyp_files(directory: Path) -> List[Path]:
    """Return sorted .yyp files in a directory."""
    try:
        return sorted(directory.glob("*.yyp"))
    except Exception:
        return []


def _search_upwards_for_yyp(start_dir: Path) -> Path | None:
    """
    Search upward from start_dir for a directory that contains a .yyp file.
    Returns the directory containing the .yyp, or None.
    """
    start_dir = Path(start_dir).resolve()
    for candidate in [start_dir, *start_dir.parents]:
        if _list_yyp_files(candidate):
            return candidate
    return None


def _search_upwards_for_gamemaker_yyp(start_dir: Path) -> Path | None:
    """
    Search upward from start_dir for a 'gamemaker/' sibling that contains a .yyp.
    This supports running commands from repo root or other subdirectories.
    """
    start_dir = Path(start_dir).resolve()
    for candidate in [start_dir, *start_dir.parents]:
        gm = candidate / "gamemaker"
        if gm.exists() and gm.is_dir() and _list_yyp_files(gm):
            return gm
    return None


def resolve_project_directory(project_root_arg: str | Path | None = None) -> Path:
    """
    Resolve the GameMaker project directory that contains the .yyp file.

    Resolution order:
    1) explicit --project-root argument (if provided and not ".")
    2) GM_PROJECT_ROOT or PROJECT_ROOT environment variable (if set)
    3) upward search from current working directory for a .yyp
    4) upward search for a 'gamemaker/' directory containing a .yyp

    Returns:
        Path to directory containing the .yyp file.

    Raises:
        FileNotFoundError if no project could be found.
    """
    candidates: List[Path] = []

    # 1) explicit CLI argument
    if project_root_arg is not None:
        arg_str = str(project_root_arg).strip()
        if arg_str and arg_str != ".":
            candidates.append(Path(arg_str))

    # 2) environment variable
    for env_key in ("GM_PROJECT_ROOT", "PROJECT_ROOT"):
        env_val = os.environ.get(env_key)
        if env_val:
            candidates.append(Path(env_val))

    # 3/4) current working directory as a start point for searches
    candidates.append(Path.cwd())

    tried: List[str] = []
    for raw in candidates:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()

        if p.is_file():
            p = p.parent

        tried.append(str(p))

        if not p.exists() or not p.is_dir():
            continue

        # Direct .yyp in the directory
        if _list_yyp_files(p):
            return p

        # Common layout: project root contains a gamemaker/ folder holding the .yyp
        gm = p / "gamemaker"
        if gm.exists() and gm.is_dir() and _list_yyp_files(gm):
            return gm

        # Upward search for a .yyp from this point (handles being in subfolders)
        found = _search_upwards_for_yyp(p)
        if found:
            return found

        # Upward search for gamemaker/ containing a .yyp (handles being at repo root)
        found_gm = _search_upwards_for_gamemaker_yyp(p)
        if found_gm:
            return found_gm

    raise FileNotFoundError(
        "No GameMaker project (.yyp) found.\n"
        f"Tried: {', '.join(tried)}\n"
        "Fix: cd into the directory that contains your .yyp, or pass --project-root, "
        "or set GM_PROJECT_ROOT or PROJECT_ROOT to the absolute path."
    )

def find_yyp_file():
    """Find the main .yyp file in the current directory."""
    yyp_files = [f for f in os.listdir('.') if f.endswith('.yyp')]
    if not yyp_files:
        raise FileNotFoundError("No .yyp file found in current directory")
    if len(yyp_files) > 1:
        raise ValueError(f"Multiple .yyp files found: {yyp_files}")
    return yyp_files[0]

def check_resource_conflicts(yyp_data, resource_name, resource_path):
    """
    Check for resource conflicts before creation.
    Returns (can_create, conflict_type, message)
    """
    resources = yyp_data.get('resources', [])
    
    for resource in resources:
        existing_name = resource.get('id', {}).get('name')
        existing_path = resource.get('id', {}).get('path')
        
        if existing_name == resource_name:
            if existing_path == resource_path:
                return False, 'exact_duplicate', f"Resource '{resource_name}' already registered with path '{resource_path}'"
            else:
                return False, 'name_conflict', f"Resource name '{resource_name}' already exists but points to '{existing_path}' instead of '{resource_path}'. Clean up the duplicate first."
        elif existing_path == resource_path:
            return False, 'path_conflict', f"Path '{resource_path}' already used by resource '{existing_name}'"
    
    return True, None, None

def find_duplicate_resources(yyp_data):
    """
    Find all resources with duplicate names in the project.
    Returns dict of {resource_name: [list of conflicting entries]}
    """
    resources = yyp_data.get('resources', [])
    name_to_entries = {}
    
    for i, resource in enumerate(resources):
        name = resource.get('id', {}).get('name')
        if name:
            if name not in name_to_entries:
                name_to_entries[name] = []
            name_to_entries[name].append({
                'index': i,
                'name': name,
                'path': resource.get('id', {}).get('path'),
                'entry': resource
            })
    
    # Return only duplicates
    return {name: entries for name, entries in name_to_entries.items() if len(entries) > 1}

def dedupe_resources(yyp_data, interactive=True):
    """
    Remove duplicate resource entries from the project.
    Returns (modified_data, removed_count, report)
    """
    duplicates = find_duplicate_resources(yyp_data)
    removed_count = 0
    report = []
    
    if not duplicates:
        return yyp_data, 0, ["No duplicate resources found."]
    
    resources = yyp_data.get('resources', [])
    new_resources = []
    
    for resource_name, entries in duplicates.items():
        report.append(f"\n[SCAN] Found {len(entries)} entries for '{resource_name}':")
        
        for entry in entries:
            report.append(f"  - Index {entry['index']}: {entry['path']}")
        
        if interactive:
            print(f"\nFound {len(entries)} entries for '{resource_name}':")
            for i, entry in enumerate(entries):
                print(f"  {i}: {entry['path']}")
            
            while True:
                try:
                    choice = input(f"Keep which entry? (0-{len(entries)-1}, or 'a' to keep first): ").strip().lower()
                    if choice == 'a':
                        keep_index = 0
                        break
                    keep_index = int(choice)
                    if 0 <= keep_index < len(entries):
                        break
                    print(f"Please enter a number between 0 and {len(entries)-1}")
                except ValueError:
                    print("Please enter a valid number or 'a'")
            
            kept_entry = entries[keep_index]
            report.append(f"  [OK] Keeping: {kept_entry['path']}")
            
            # Remove others
            for i, entry in enumerate(entries):
                if i != keep_index:
                    report.append(f"  [ERROR] Removing: {entry['path']}")
                    removed_count += 1
        else:
            # Non-interactive: keep first occurrence
            kept_entry = entries[0]
            report.append(f"  [OK] Keeping first: {kept_entry['path']}")
            
            for entry in entries[1:]:
                report.append(f"  [ERROR] Removing: {entry['path']}")
                removed_count += 1
    
    # Rebuild resources list without duplicates
    processed_names = set()
    for resource in resources:
        name = resource.get('id', {}).get('name')
        if name in duplicates:
            if name not in processed_names:
                # Keep first occurrence of duplicated name
                new_resources.append(resource)
                processed_names.add(name)
            # Skip subsequent duplicates
        else:
            # Keep non-duplicated resources
            new_resources.append(resource)
    
    yyp_data['resources'] = new_resources
    return yyp_data, removed_count, report

def update_yyp_file(resource_entry):
    """Add a resource entry to the main .yyp file with duplicate checking."""
    yyp_file = find_yyp_file()
    
    try:
        project_data = load_json(yyp_file)
    except Exception as e:
        print(f"Error loading project file: {e}")
        return False
    
    # Check for conflicts before creating
    resource_name = resource_entry['id']['name']
    resource_path = resource_entry['id']['path']
    
    can_create, conflict_type, message = check_resource_conflicts(project_data, resource_name, resource_path)
    
    if not can_create:
        print(f"[ERROR] Resource creation failed: {message}")
        if conflict_type == 'name_conflict':
            print("[INFO] Suggestion: Use 'gms maintenance dedupe-resources' to clean up duplicates")
        return False
    
    # Add the resource in alphabetical order
    resources = project_data.get('resources', [])
    
    # Find the correct position to insert (alphabetical by name)
    insert_pos = 0
    
    for i, resource in enumerate(resources):
        if resource['id']['name'] > resource_name:
            insert_pos = i
            break
        insert_pos = i + 1
    
    resources.insert(insert_pos, resource_entry)
    project_data['resources'] = resources
    
    try:
        save_json(project_data, yyp_file)
        print(f"[OK] Added '{resource_name}' to {yyp_file}")
        return True
    except Exception as e:
        print(f"Error saving project file: {e}")
        return False

def validate_parent_path(parent_path):
    """Validate that a parent folder path exists in the project's .yyp Folders list.
    
    If the folder is missing the process now aborts instead of only emitting
    a warning - this prevents dangling assets from being created.
    """
    if not parent_path:
        return True  # No parent path is valid
    
    try:
        # Load the .yyp file to check Folders list
        yyp_file = find_yyp_file()
        project_data = load_json(yyp_file)
        folders = project_data.get("Folders", [])
        
        # Check if the parent_path exists in the Folders list
        folder_paths = {folder.get("folderPath", "") for folder in folders}
        
        if parent_path in folder_paths:
            return True
        
        # Folder not found -> stop immediately and show the user what went wrong
        available = "\n  - ".join(sorted(p for p in folder_paths if p))
        raise ValidationError(
            f"Parent folder path '{parent_path}' not found in project Folders list.\n"
            f"Available folder paths:\n  - {available}"
        )
            
    except GMSError:
        # Re-raise GMS errors
        raise
    except Exception as e:
        raise ValidationError(f"Error validating parent path '{parent_path}': {e}")

def remove_folder_from_yyp(folder_path, force=False, dry_run=False):
    """
    Remove a folder from the .yyp file.
    
    Args:
        folder_path: The folder path to remove (e.g., "folders/Cursor Test.yy")
        force: If True, skip safety checks for assets in the folder
        dry_run: If True, don't actually save changes, just report what would happen
    
    Returns:
        (success: bool, message: str, assets_in_folder: list)
    """
    yyp_file = find_yyp_file()
    
    try:
        project_data = load_json(yyp_file)
    except Exception as e:
        return False, f"Error loading project file: {e}", []
    
    # Check if folder exists
    folders = project_data.get("Folders", [])
    folder_to_remove = None
    
    for folder in folders:
        if folder.get("folderPath") == folder_path:
            folder_to_remove = folder
            break
    
    if not folder_to_remove:
        return False, f"Folder '{folder_path}' not found in project", []
    
    # Check for assets that reference this folder (unless force is True)
    assets_in_folder = []
    if not force:
        resources = project_data.get("resources", [])
        
        for resource in resources:
            resource_path = resource.get("id", {}).get("path", "")
            if resource_path:
                try:
                    # Load the resource file to check its parent path
                    resource_file_path = resource_path
                    if os.path.exists(resource_file_path):
                        resource_data = load_json(resource_file_path)
                        parent_path = resource_data.get("parent", {}).get("path", "")
                        if parent_path == folder_path:
                            assets_in_folder.append({
                                "name": resource.get("id", {}).get("name", ""),
                                "path": resource_path,
                                "type": resource_data.get("resourceType", "Unknown")
                            })
                except Exception:
                    # If we can't read the resource file, skip it
                    pass
        
        if assets_in_folder:
            asset_list = "\n".join([f"  - {asset['name']} ({asset['type']})" for asset in assets_in_folder])
            return False, f"Cannot remove folder '{folder_path}' - it contains {len(assets_in_folder)} assets:\n{asset_list}\n\nMove or remove these assets first, or use --force to override.", assets_in_folder
    
    # Remove the folder from the Folders list
    updated_folders = [f for f in folders if f.get("folderPath") != folder_path]
    project_data["Folders"] = updated_folders
    
    if dry_run:
        folder_name = folder_to_remove.get("name", folder_path)
        return True, f"Would remove folder '{folder_name}' from project", assets_in_folder
    else:
        try:
            save_json(project_data, yyp_file)
            folder_name = folder_to_remove.get("name", folder_path)
            return True, f"Successfully removed folder '{folder_name}' from project", assets_in_folder
        except Exception as e:
            return False, f"Error saving project file: {e}", assets_in_folder

def list_folders_in_yyp():
    """
    List all folders in the .yyp file.
    
    Returns:
        (success: bool, folders: list, message: str)
    """
    yyp_file = find_yyp_file()
    
    try:
        project_data = load_json(yyp_file)
        folders = project_data.get("Folders", [])
        
        folder_list = []
        for folder in folders:
            folder_list.append({
                "name": folder.get("name", ""),
                "path": folder.get("folderPath", ""),
                "full_entry": folder
            })
        
        # Sort by name for consistent output
        folder_list.sort(key=lambda f: f["name"].lower())
        
        return True, folder_list, f"Found {len(folder_list)} folders in project"
        
    except Exception as e:
        return False, [], f"Error loading project file: {e}" 
