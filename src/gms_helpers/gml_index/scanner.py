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
        "function": re.compile(
            r'^\s*function\s+(\w+)\s*\(([^)]*)\)\s*(constructor)?\s*\{?',
            re.MULTILINE
        ),
        # enum EnumName { VALUE1, VALUE2 }
        "enum": re.compile(
            r'^\s*enum\s+(\w+)\s*\{([^}]*)\}',
            re.MULTILINE | re.DOTALL
        ),
        # #macro NAME value
        "macro": re.compile(
            r'^\s*#macro\s+(\w+)\s+(.+?)$',
            re.MULTILINE
        ),
        # globalvar name;
        "globalvar": re.compile(
            r'^\s*globalvar\s+(\w+)\s*;',
            re.MULTILINE
        ),
    }
    
    # Pattern for identifying word tokens (potential references)
    WORD_PATTERN = re.compile(r'\b([a-zA-Z_]\w*)\b')
    
    # Built-in GML functions and constants to exclude from references
    # This is a minimal set - could be expanded
    BUILTINS = {
        'if', 'else', 'while', 'for', 'do', 'until', 'repeat', 'switch', 
        'case', 'default', 'break', 'continue', 'return', 'exit', 'with',
        'var', 'globalvar', 'enum', 'function', 'constructor', 'new',
        'true', 'false', 'undefined', 'noone', 'all', 'self', 'other',
        'global', 'local', 'static', 'try', 'catch', 'finally', 'throw',
        'and', 'or', 'not', 'xor', 'mod', 'div',
    }

    def __init__(self):
        self.symbols: List[Symbol] = []
        self.references: List[SymbolReference] = []
    
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
            content = file_path.read_text(encoding='utf-8', errors='replace')
        except Exception:
            return [], []
        
        lines = content.split('\n')
        
        # Extract doc comments for functions
        doc_comments = self._extract_doc_comments(lines)
        
        # Find function definitions
        self._scan_functions(content, file_path, doc_comments)
        
        # Find enum definitions
        self._scan_enums(content, file_path)
        
        # Find macro definitions
        self._scan_macros(content, file_path)
        
        # Find globalvar declarations
        self._scan_globalvars(content, file_path)
        
        # Find references (word tokens that could be symbol usages)
        self._scan_references(content, file_path, lines)
        
        return self.symbols, self.references
    
    def _extract_doc_comments(self, lines: List[str]) -> dict:
        """Extract JSDoc-style comments that precede functions.
        
        Returns dict mapping line number -> doc comment text
        """
        doc_comments = {}
        current_doc = []
        in_doc = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            if stripped.startswith('///') or stripped.startswith('/**'):
                in_doc = True
                current_doc.append(stripped.lstrip('/*').strip())
            elif in_doc and (stripped.startswith('*') or stripped.startswith('//')):
                current_doc.append(stripped.lstrip('*/').strip())
            elif in_doc:
                if current_doc:
                    # Store doc comment for the next non-empty line
                    doc_comments[i] = '\n'.join(current_doc)
                current_doc = []
                in_doc = False
                
        return doc_comments
    
    def _scan_functions(self, content: str, file_path: Path, doc_comments: dict):
        """Scan for function definitions."""
        for match in self.PATTERNS["function"].finditer(content):
            name = match.group(1)
            params_str = match.group(2)
            is_constructor = match.group(3) is not None
            
            # Parse parameters
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            
            # Calculate line number
            line_num = content[:match.start()].count('\n') + 1
            
            # Check for doc comment
            doc = doc_comments.get(line_num - 1) or doc_comments.get(line_num)
            
            kind = SymbolKind.CONSTRUCTOR if is_constructor else SymbolKind.FUNCTION
            
            symbol = Symbol(
                name=name,
                kind=kind,
                location=SymbolLocation(
                    file_path=file_path,
                    line=line_num,
                    column=match.start() - content.rfind('\n', 0, match.start())
                ),
                doc_comment=doc,
                parameters=params
            )
            self.symbols.append(symbol)
    
    def _scan_enums(self, content: str, file_path: Path):
        """Scan for enum definitions and their values."""
        for match in self.PATTERNS["enum"].finditer(content):
            enum_name = match.group(1)
            enum_body = match.group(2)
            
            line_num = content[:match.start()].count('\n') + 1
            
            # Add the enum itself
            self.symbols.append(Symbol(
                name=enum_name,
                kind=SymbolKind.ENUM,
                location=SymbolLocation(file_path=file_path, line=line_num)
            ))
            
            # Parse enum values
            # Handle: VALUE, VALUE = 0, VALUE = "string"
            value_pattern = re.compile(r'(\w+)\s*(?:=\s*[^,}]+)?')
            for value_match in value_pattern.finditer(enum_body):
                value_name = value_match.group(1)
                if value_name:
                    # Calculate approximate line for the value
                    value_line = line_num + enum_body[:value_match.start()].count('\n')
                    self.symbols.append(Symbol(
                        name=value_name,
                        kind=SymbolKind.ENUM_VALUE,
                        location=SymbolLocation(file_path=file_path, line=value_line),
                        parent_enum=enum_name
                    ))
    
    def _scan_macros(self, content: str, file_path: Path):
        """Scan for macro definitions."""
        for match in self.PATTERNS["macro"].finditer(content):
            name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            
            self.symbols.append(Symbol(
                name=name,
                kind=SymbolKind.MACRO,
                location=SymbolLocation(file_path=file_path, line=line_num)
            ))
    
    def _scan_globalvars(self, content: str, file_path: Path):
        """Scan for globalvar declarations."""
        for match in self.PATTERNS["globalvar"].finditer(content):
            name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            
            self.symbols.append(Symbol(
                name=name,
                kind=SymbolKind.GLOBALVAR,
                location=SymbolLocation(file_path=file_path, line=line_num)
            ))
    
    def _scan_references(self, content: str, file_path: Path, lines: List[str]):
        """Scan for potential symbol references."""
        # Get names of symbols defined in this file to help with filtering
        defined_here = {s.name for s in self.symbols}
        
        for line_num, line in enumerate(lines, start=1):
            # Skip comment lines
            stripped = line.strip()
            if stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*'):
                continue
            
            # Remove string literals to avoid false positives
            clean_line = re.sub(r'"[^"]*"', '""', line)
            clean_line = re.sub(r"'[^']*'", "''", clean_line)
            
            # Remove inline comments
            if '//' in clean_line:
                clean_line = clean_line[:clean_line.index('//')]
            
            for match in self.WORD_PATTERN.finditer(clean_line):
                word = match.group(1)
                
                # Skip builtins and very short names
                if word in self.BUILTINS or len(word) < 2:
                    continue
                    
                # Skip if it looks like a local variable (lowercase start, short)
                # This is a heuristic - not perfect
                if word[0].islower() and len(word) < 4 and word not in defined_here:
                    continue
                
                self.references.append(SymbolReference(
                    symbol_name=word,
                    location=SymbolLocation(
                        file_path=file_path,
                        line=line_num,
                        column=match.start()
                    ),
                    context=line.strip()[:100]  # First 100 chars for context
                ))
