import json
import urllib.request
import urllib.error
from importlib.metadata import version, PackageNotFoundError
import logging

logger = logging.getLogger(__name__)

def get_current_version() -> str:
    """Get the current version of the gms-mcp package."""
    try:
        return version("gms-mcp")
    except PackageNotFoundError:
        # Fallback for development installs or if not installed via pip
        return "0.0.0"

def get_latest_version_pypi() -> str | None:
    """Check PyPI for the latest version of gms-mcp."""
    url = "https://pypi.org/pypi/gms-mcp/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gms-mcp-update-checker"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data["info"]["version"]
    except Exception as e:
        logger.debug(f"Failed to check PyPI for updates: {e}")
        return None

def get_latest_version_github() -> str | None:
    """Check GitHub for the latest release version of gms-mcp."""
    url = "https://api.github.com/repos/Ampersand-Game-Studios/gms-mcp/releases/latest"
    try:
        # GitHub API requires a User-Agent
        req = urllib.request.Request(url, headers={"User-Agent": "gms-mcp-update-checker"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            tag_name = data["tag_name"]
            # Remove 'v' prefix if present
            if tag_name.startswith("v"):
                return tag_name[1:]
            return tag_name
    except Exception as e:
        logger.debug(f"Failed to check GitHub for updates: {e}")
        return None

def check_for_updates():
    """
    Check if a newer version of gms-mcp is available.
    Returns a dict with update information.
    """
    current = get_current_version()
    
    # Check both PyPI and GitHub
    pypi_latest = get_latest_version_pypi()
    github_latest = get_latest_version_github()
    
    # Take the "maximum" version if we can, otherwise just pick one that isn't None
    # Since we aren't using a proper version parser to avoid dependencies, 
    # we'll just check if either is different from current.
    
    latest = current
    source = None
    
    if pypi_latest and pypi_latest != current:
        latest = pypi_latest
        source = "PyPI"
    elif github_latest and github_latest != current:
        latest = github_latest
        source = "GitHub"

    if latest != current:
        url = "https://pypi.org/project/gms-mcp/" if source == "PyPI" else "https://github.com/Ampersand-Game-Studios/gms-mcp/releases/latest"
        return {
            "update_available": True,
            "current_version": current,
            "latest_version": latest,
            "source": source,
            "message": f"A newer version of gms-mcp is available via {source}: {latest} (current: {current}). Update with 'pip install --upgrade gms-mcp' or check {url}",
            "url": url
        }
    
    return {
        "update_available": False,
        "current_version": current,
        "latest_version": current,
        "message": "You are running the latest version of gms-mcp."
    }
