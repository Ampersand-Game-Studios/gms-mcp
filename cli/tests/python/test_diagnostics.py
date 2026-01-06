import unittest
from pathlib import Path
import tempfile
import shutil
import json
import os
from gms_helpers.diagnostics import Diagnostic, CODE_JSON_INVALID
from gms_helpers.maintenance.lint import LintIssue, ProjectLinter
from gms_helpers.commands.diagnostics_commands import handle_diagnostics

class TestDiagnostics(unittest.TestCase):
    def test_lint_to_diagnostic(self):
        issue = LintIssue(
            severity='error',
            category='json',
            file_path='test.yy',
            message='Invalid JSON',
            line_number=10
        )
        diag = issue.to_diagnostic()
        self.assertEqual(diag.severity, 'error')
        self.assertEqual(diag.code, CODE_JSON_INVALID)
        self.assertEqual(diag.line, 10)
        self.assertTrue(diag.can_auto_fix)

    def test_handle_diagnostics_quick(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            # Create a dummy project file
            yyp_path = project_root / "test.yyp"
            with open(yyp_path, 'w') as f:
                f.write('{"resources": []}')
            
            # Create an invalid JSON file
            bad_yy = project_root / "bad.yy"
            with open(bad_yy, 'w') as f:
                f.write('{"invalid": }')
            
            # Use a mock args object
            class Args:
                pass
            args = Args()
            args.project_root = str(project_root)
            args.depth = 'quick'
            args.include_info = False
            
            # We need to mock find_yyp_file or set CWD to project_root
            old_cwd = os.getcwd()
            os.chdir(project_root)
            try:
                result = handle_diagnostics(args)
                self.assertFalse(result['ok'])
                self.assertTrue(any(d['code'] == CODE_JSON_INVALID for d in result['diagnostics']))
                self.assertEqual(result['summary']['error'], 1)
            finally:
                os.chdir(old_cwd)

if __name__ == '__main__':
    unittest.main()
