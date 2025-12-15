"""
Asset Linting - Project validation and issue detection
"""

import os
import glob
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from pathlib import Path

from ..utils import load_json, validate_name, find_yyp_file


@dataclass
class LintIssue:
    """Represents a project validation issue."""
    severity: str  # 'error', 'warning', 'info'
    category: str  # 'json', 'naming', 'structure', 'reference'
    file_path: str
    message: str
    line_number: Optional[int] = None
    
    def __str__(self):
        severity_icon = {
            'error': '[ERROR]',
            'warning': '[WARN]',
            'info': '[INFO]'
        }
        icon = severity_icon.get(self.severity, '?')
        location = f"{self.file_path}"
        if self.line_number:
            location += f":{self.line_number}"
        return f"{icon} [{self.category}] {location}: {self.message}"


class ProjectLinter:
    """Scans and validates a GameMaker project."""
    
    def __init__(self, project_root: str = '.'):
        self.project_root = Path(project_root)
        self.issues: List[LintIssue] = []
        self.yyp_path = None
        self.yyp_data = None
    
    def scan_project(self) -> List[LintIssue]:
        """Perform a comprehensive project scan."""
        self.issues.clear()
        
        # Load main project file
        try:
            self.yyp_path = find_yyp_file()
            self.yyp_data = load_json(self.yyp_path)
        except Exception as e:
            self.issues.append(LintIssue(
                severity='error',
                category='json',
                file_path=str(self.yyp_path or 'unknown'),
                message=f"Failed to load project file: {e}"
            ))
            return self.issues
        
        # Scan all .yy files
        self._scan_yy_files()
        
        # Validate naming conventions
        self._validate_naming_conventions()
        
        # Check project structure
        self._validate_project_structure()
        
        return self.issues
    
    def _scan_yy_files(self):
        """Scan all .yy files for JSON validity."""
        yy_pattern = str(self.project_root / "**" / "*.yy")
        yy_files = glob.glob(yy_pattern, recursive=True)
        
        for yy_file in yy_files:
            # Skip options files - they have a special format
            if 'options' in yy_file.lower():
                continue
                
            try:
                load_json(yy_file)
            except Exception as e:
                self.issues.append(LintIssue(
                    severity='error',
                    category='json',
                    file_path=yy_file,
                    message=f"Invalid JSON: {e}"
                ))
    
    def _validate_options_file(self, file_path: str):
        """Validate GameMaker options files which have special format."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Options files have format: version_header|{json_content}
            if '|{' in content:
                json_part = content.split('|', 1)[1]
                # Use our load_json logic to handle trailing commas
                try:
                    import json
                    json.loads(json_part)
                except json.JSONDecodeError:
                    # Try with trailing commas stripped
                    import re
                    json_part = re.sub(r',(\s*[}\]])', r'\1', json_part)
                    json.loads(json_part)
            else:
                # If no pipe separator, try as regular JSON using our load_json function
                load_json(file_path)
                
        except Exception as e:
            raise ValueError(f"Invalid options file format: {e}")
    
    def _validate_naming_conventions(self):
        """Check asset naming conventions."""
        if not self.yyp_data:
            return
        
        resources = self.yyp_data.get('resources', [])
        
        for resource in resources:
            resource_id = resource.get('id', {})
            name = resource_id.get('name', '')
            path = resource_id.get('path', '')
            
            if not name:
                continue
            
            # Determine asset type from path
            asset_type = self._get_asset_type_from_path(path)
            if not asset_type:
                continue
            
            # Skip naming validation for constructor scripts
            if asset_type == 'script' and self._is_constructor_script(path):
                continue
            
            try:
                validate_name(name, asset_type)
            except ValueError as e:
                self.issues.append(LintIssue(
                    severity='warning',
                    category='naming',
                    file_path=path,
                    message=str(e)
                ))
    
    def _validate_project_structure(self):
        """Check for structural issues."""
        if not self.yyp_data:
            return
        
        resources = self.yyp_data.get('resources', [])
        
        # Check for missing files (skip options files)
        for resource in resources:
            resource_id = resource.get('id', {})
            path = resource_id.get('path', '')
            
            # Skip options files
            if '/options/' in path.replace('\\', '/') or '\\options\\' in path:
                continue
                
            if path and not path.startswith('folders/') and not os.path.exists(path):
                self.issues.append(LintIssue(
                    severity='error',
                    category='reference',
                    file_path=path,
                    message="Referenced file does not exist"
                ))
        
        # Check for duplicate names
        names_seen = set()
        for resource in resources:
            resource_id = resource.get('id', {})
            name = resource_id.get('name', '')
            
            if name in names_seen:
                self.issues.append(LintIssue(
                    severity='error',
                    category='structure',
                    file_path=self.yyp_path,
                    message=f"Duplicate resource name: {name}"
                ))
            names_seen.add(name)
    
    def _get_asset_type_from_path(self, path: str) -> Optional[str]:
        """Determine asset type from file path."""
        if '/scripts/' in path:
            return 'script'
        elif '/objects/' in path:
            return 'object'
        elif '/sprites/' in path:
            return 'sprite'
        elif '/rooms/' in path:
            return 'room'
        return None
    
    def _is_constructor_script(self, path: str) -> bool:
        """Check if a script contains constructor pattern."""
        import re
        import os
        
        try:
            # Convert .yy path to .gml path
            gml_path = path.replace('.yy', '.gml')
            if not os.path.exists(gml_path):
                return False
                
            with open(gml_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Look for pattern: function SomeName() constructor {
                # Allow for optional parameters and whitespace variations
                pattern = r'function\s+[A-Z][a-zA-Z0-9]*\s*\([^)]*\)\s*constructor\s*\{'
                return bool(re.search(pattern, content))
        except Exception:
            # If we can't read the file, assume it's not a constructor
            return False
    
    def get_summary(self) -> Dict[str, int]:
        """Get issue count summary."""
        summary = {'error': 0, 'warning': 0, 'info': 0}
        for issue in self.issues:
            summary[issue.severity] = summary.get(issue.severity, 0) + 1
        return summary
    
    def has_errors(self) -> bool:
        """Check if any errors were found."""
        return any(issue.severity == 'error' for issue in self.issues)


def lint_project(project_root: str = '.') -> List[LintIssue]:
    """Convenience function to lint a project."""
    linter = ProjectLinter(project_root)
    return linter.scan_project()


def print_lint_report(issues: List[LintIssue]):
    """Print a formatted lint report."""
    if not issues:
        print("[OK] No issues found! Project looks good.")
        return
    
    # Group issues by severity
    errors = [i for i in issues if i.severity == 'error']
    warnings = [i for i in issues if i.severity == 'warning']
    info = [i for i in issues if i.severity == 'info']
    
    # Print summary
    total = len(issues)
    print(f"\n[INFO] Lint Report: {total} issue(s) found")
    print(f"   Errors: {len(errors)}")
    print(f"   Warnings: {len(warnings)}")
    print(f"   Info: {len(info)}")
    print("-" * 50)
    
    # Print issues by severity
    for issue_list, title in [(errors, "ERRORS"), (warnings, "WARNINGS"), (info, "INFO")]:
        if issue_list:
            print(f"\n{title}:")
            for issue in issue_list:
                print(f"  {issue}")
    
    print(f"\n{'[ERROR] Fix errors before proceeding!' if errors else '[OK] No critical errors found.'}") 
