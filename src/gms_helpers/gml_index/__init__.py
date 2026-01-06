"""GML Symbol Indexing Engine.

Provides code intelligence features for GameMaker projects:
- Symbol definitions (functions, enums, macros, globalvars)
- Reference tracking (where symbols are used)
- Cross-file navigation
"""

from .symbols import Symbol, SymbolKind, SymbolLocation, SymbolReference
from .scanner import GMLScanner
from .index import GMLIndex

__all__ = [
    "Symbol",
    "SymbolKind", 
    "SymbolLocation",
    "SymbolReference",
    "GMLScanner",
    "GMLIndex",
]
