"""Import and source boundaries. These tests do not open Bluetooth."""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PACKAGE = SRC / "soundcore_diag"


class SafetyTests(unittest.TestCase):
    def test_package_does_not_import_bleak_except_live_functions(self) -> None:
        for path in PACKAGE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                self.assertFalse(_imports_bleak(node), path.name)
            if path.name != "live.py":
                for node in ast.walk(tree):
                    self.assertFalse(_imports_bleak(node), path.name)
            for node in tree.body:
                self.assertFalse(_imports_named(node, "sounddevice"), path.name)

    def test_sources_do_not_persist_or_upload_audio(self) -> None:
        banned = ("urllib", "requests", "websocket", "write_bytes", ".wav", "unpair")
        for path in PACKAGE.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for word in banned:
                self.assertNotIn(word, text, f"{path.name} contains {word}")
            self.assertNotIn("open(", text, path.name)
        live = (PACKAGE / "live.py").read_text(encoding="utf-8")
        self.assertIn("pair=False", live)
        self.assertNotIn("0x18", live)

    def test_cli_safe_commands_do_not_import_bleak(self) -> None:
        code = """
import sys
from soundcore_diag.cli import main
assert main([]) == 0
assert main(["--help"]) == 0
assert main(["--self-test"]) == 0
assert main(["live"]) == 2
assert main(["live", "--scan"]) == 2
assert main(["live", "--consent"]) == 2
assert main(["live", "--consent", "--scan", "--address", "AA:BB:CC:DD:EE:FF"]) == 2
assert main(["live", "--consent", "--address", "00:00:00:00:00:00"]) == 2
assert main(["live", "--consent", "--seconds", "31", "--address", "AA:BB:CC:DD:EE:FF"]) == 2
assert main(["live", "--consent", "--to-cable"]) == 2
assert main(["live", "--consent", "--to-cable", "--scan"]) == 2
assert main(["live", "--consent", "--to-cable", "--seconds", "999999", "--address", "AA:BB:CC:DD:EE:FF"]) == 2
check = main(["--check-env"])
assert check in (0, 2)
assert "bleak" not in sys.modules
assert "sounddevice" not in sys.modules
assert "soundcore_diag.live" not in sys.modules
print("safe-cli-ok")
"""
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env={**_env(), "PYTHONPATH": str(SRC)},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("safe-cli-ok", completed.stdout)
        self.assertIn("自检通过", completed.stdout)

    def test_importing_live_module_does_not_import_bleak(self) -> None:
        code = """
import sys
import soundcore_diag.live
assert "bleak" not in sys.modules
print("live-import-ok")
"""
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env={**_env(), "PYTHONPATH": str(SRC)},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("live-import-ok", completed.stdout)


def _imports_named(node: ast.AST, name: str) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name == name or alias.name.startswith(name + ".") for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        return bool(node.module and (node.module == name or node.module.startswith(name + ".")))
    return False


def _imports_bleak(node: ast.AST) -> bool:
    return _imports_named(node, "bleak")


def _env() -> dict[str, str]:
    import os

    return dict(os.environ)


if __name__ == "__main__":
    unittest.main()
