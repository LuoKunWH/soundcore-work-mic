"""The version label shown in the tray panel and written to tray.log.

It is the package version plus the short commit id of the checkout the tray
runs from, so every update shows a different label even when the version
number did not change. The commit is read from the .git folder directly,
without running git; a copy without .git shows the version alone.
"""

from __future__ import annotations

from pathlib import Path

from soundcore_diag import __version__

ROOT = Path(__file__).resolve().parents[2]


def _commit(root: Path) -> tuple[str, str]:
    """(short commit id, branch name) of the checkout, or ("", "")."""
    git = root / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head[:7], ""
        ref = head[len("ref: "):]
        branch = ref.removeprefix("refs/heads/")
        loose = git / ref
        if loose.is_file():
            return loose.read_text(encoding="utf-8").strip()[:7], branch
        packed = git / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0][:7], branch
    except (OSError, UnicodeDecodeError):
        pass
    return "", ""


def label(root: Path | None = None, with_branch: bool = True) -> str:
    """For example "v0.2.1 · 1a2b3c4", with the branch added when it is not main."""
    commit, branch = _commit(root or ROOT)
    text = f"v{__version__}"
    if commit:
        text += f" · {commit}"
    if with_branch and branch and branch != "main":
        text += f" · {branch}"
    return text
