"""Catch accidental escaped newlines that silently comment out scheduler imports."""
import ast
import unittest
from pathlib import Path

class ScannerStartupTests(unittest.TestCase):
    def test_scanner_import_and_start_are_executable(self):
        source=Path("app.py").read_text(encoding="utf-8")
        tree=ast.parse(source)
        imports=[n for n in tree.body if isinstance(n,ast.ImportFrom) and n.module=="server_scan"]
        self.assertTrue(any(any(a.name=="start" and a.asname=="start_watch_scan" for a in n.names) for n in imports))
        funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="bootstrap_watch_scan_in_http_worker"]
        self.assertEqual(len(funcs),1)
        self.assertTrue(any(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
            and isinstance(n.value.func,ast.Name) and n.value.func.id=="start_watch_scan"
            for n in funcs[0].body))
        self.assertTrue(any(isinstance(d,ast.Attribute) and d.attr=="before_request" for d in funcs[0].decorator_list))
    def test_source_does_not_hide_import_in_comment(self):
        source=Path("app.py").read_text(encoding="utf-8")
        self.assertNotIn(r"\nfrom server_scan",source)

if __name__=="__main__":
    unittest.main()
