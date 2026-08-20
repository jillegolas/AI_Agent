import tempfile
import unittest
from pathlib import Path

from bug_fix_agent import analyze


class BugFixAgentTests(unittest.TestCase):
    def test_detects_and_fixes_identity_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.py"
            path.write_text("value = 10\nif value is 10:\n    print('ok')\n", encoding="utf-8")
            report = analyze(str(path), apply=True, test_command=["python", "-m", "py_compile", "sample.py"])
            self.assertEqual(report.applied_fixes, 1)
            self.assertTrue(any(item.rule == "identity-comparison" and item.fixed for item in report.findings))
            self.assertIn("==", path.read_text(encoding="utf-8"))

    def test_import_errors_block_production_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.py"
            path.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
            report = analyze(str(path), test_command=["python", "-m", "py_compile", "broken.py"])
            self.assertTrue(report.import_errors)
            self.assertFalse(report.production_ready)

    def test_sql_has_extension_point(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "query.sql"
            path.write_text("select 1;\n", encoding="utf-8")
            report = analyze(str(path), language="sql", test_command=["python", "-c", "print('sql checks')"])
            self.assertEqual(report.language, "sql")
            self.assertTrue(any(item.rule == "tooling-required" for item in report.findings))


if __name__ == "__main__":
    unittest.main()
