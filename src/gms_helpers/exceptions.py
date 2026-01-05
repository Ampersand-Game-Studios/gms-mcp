"""Custom exceptions for GMS helpers with JSON-RPC error code support."""
from typing import Optional

class GMSError(Exception):
    """Base exception for all GMS helper operations."""
    exit_code: int = 1
    json_rpc_code: int = -32000  # Generic application error
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

class ProjectNotFoundError(GMSError):
    """No .yyp file found in project directory."""
    exit_code = 2
    json_rpc_code = -32001

class AssetExistsError(GMSError):
    """Asset with this name already exists."""
    exit_code = 3
    json_rpc_code = -32002

class AssetNotFoundError(GMSError):
    """Referenced asset does not exist."""
    exit_code = 4
    json_rpc_code = -32003

class InvalidAssetTypeError(GMSError):
    """Unrecognized or unsupported asset type."""
    exit_code = 5
    json_rpc_code = -32004

class JSONParseError(GMSError):
    """Failed to parse or load JSON file."""
    exit_code = 6
    json_rpc_code = -32005

class RuntimeNotFoundError(GMSError):
    """GameMaker runtime or Igor.exe not found."""
    exit_code = 7
    json_rpc_code = -32006

class LicenseNotFoundError(GMSError):
    """GameMaker license file not found."""
    exit_code = 8
    json_rpc_code = -32007

class ValidationError(GMSError):
    """Project validation failed."""
    exit_code = 9
    json_rpc_code = -32008
