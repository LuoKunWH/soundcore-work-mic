"""Cable endpoint selection without PortAudio or VB-CABLE."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from soundcore_diag.cable import CableSink, open_cable_input
from soundcore_diag.selftest import _check_cable


class CableTests(unittest.TestCase):
    def test_selection_rules(self) -> None:
        _check_cable()

    def test_opener_is_not_called_from_module_import(self) -> None:
        source = Path(__file__).resolve().parents[1] / "src" / "soundcore_diag" / "cable.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imported.append(ast.dump(node))
        self.assertFalse(any("sounddevice" in item for item in imported))
        self.assertTrue(callable(open_cable_input))
        self.assertTrue(callable(CableSink))


if __name__ == "__main__":
    unittest.main()
