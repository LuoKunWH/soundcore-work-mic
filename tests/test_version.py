"""The version label read from a checkout's .git folder."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from soundcore_diag import __version__, version

SHA = "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d"


class VersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.git = self.root / ".git"
        self.git.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_loose_ref_on_main(self) -> None:
        (self.git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (self.git / "refs" / "heads").mkdir(parents=True)
        (self.git / "refs" / "heads" / "main").write_text(SHA + "\n", encoding="utf-8")
        self.assertEqual(version.label(self.root), f"v{__version__} · 1a2b3c4")

    def test_packed_ref_on_a_branch(self) -> None:
        (self.git / "HEAD").write_text("ref: refs/heads/fix\n", encoding="utf-8")
        (self.git / "packed-refs").write_text(f"# pack-refs\n{SHA} refs/heads/fix\n", encoding="utf-8")
        self.assertEqual(version.label(self.root), f"v{__version__} · 1a2b3c4 · fix")
        self.assertEqual(version.label(self.root, with_branch=False), f"v{__version__} · 1a2b3c4")

    def test_detached_and_missing(self) -> None:
        (self.git / "HEAD").write_text(SHA + "\n", encoding="utf-8")
        self.assertEqual(version.label(self.root), f"v{__version__} · 1a2b3c4")
        self.assertEqual(version.label(self.root / "nowhere"), f"v{__version__}")


if __name__ == "__main__":
    unittest.main()
