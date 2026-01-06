"""Symbol data structures for GML code intelligence."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class SymbolKind(Enum):
    """Types of symbols that can be indexed."""
    FUNCTION = "function"
    SCRIPT = "script"
    ENUM = "enum"
    ENUM_VALUE = "enum_value"
    MACRO = "macro"
    GLOBALVAR = "globalvar"
    CONSTRUCTOR = "constructor"


@dataclass
class SymbolLocation:
    """Location of a symbol in a file."""
    file_path: Path
    line: int
    column: int = 0
    end_line: Optional[int] = None
    end_column: Optional[int] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "file": str(self.file_path),
            "line": self.line,
            "column": self.column,
        }
        if self.end_line is not None:
            result["end_line"] = self.end_line
        if self.end_column is not None:
            result["end_column"] = self.end_column
        return result


@dataclass
class Symbol:
    """A symbol definition in GML code."""
    name: str
    kind: SymbolKind
    location: SymbolLocation
    doc_comment: Optional[str] = None
    parameters: List[str] = field(default_factory=list)
    parent_enum: Optional[str] = None  # For enum values
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "name": self.name,
            "kind": self.kind.value,
            "location": self.location.to_dict(),
        }
        if self.doc_comment:
            result["doc"] = self.doc_comment
        if self.parameters:
            result["parameters"] = self.parameters
        if self.parent_enum:
            result["parent_enum"] = self.parent_enum
        return result


@dataclass  
class SymbolReference:
    """A reference to a symbol (usage site)."""
    symbol_name: str
    location: SymbolLocation
    context: Optional[str] = None  # Line of code for context
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "symbol": self.symbol_name,
            "location": self.location.to_dict(),
        }
        if self.context:
            result["context"] = self.context
        return result
