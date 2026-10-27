"""Smoke and regression tests for a standalone Aegean Reforge repository."""

import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from reforge.detectors import detect_source
from reforge.repair import repair_findings

PROC_TIMEOUT = 30


class ReforgeSmokeTests(unittest.TestCase):
    def test_detector_finds_a_bare_except(self):
        findings = detect_source("fixture.py", "try:\n    pass\nexcept:\n    pass\n", "abc")
        self.assertIn("bare-except", {finding.code for finding in findings})

    def test_repair_removes_a_bare_except_and_writes_a_test(self):
        root = Path(tempfile.mkdtemp(prefix="reforge_smoke_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        (root / "fixture.py").write_text("try:\n    pass\nexcept:\n    pass\n", encoding="utf-8")
        findings = detect_source("fixture.py", (root / "fixture.py").read_text(encoding="utf-8"), "abc")
        repairs = repair_findings(root, findings)
        self.assertTrue(any(repair.applied for repair in repairs))
        tree = ast.parse((root / "fixture.py").read_text(encoding="utf-8"))
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.type is None], [])

    def test_cli_help_exits_zero(self):
        done = subprocess.run([sys.executable, "-m", "reforge", "--help"], capture_output=True,
                              text=True, timeout=PROC_TIMEOUT)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("usage:", done.stdout.lower())
