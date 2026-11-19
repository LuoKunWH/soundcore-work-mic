"""Which recordings on the bean were made while it served as a microphone.

The bridge adds a file id here once it has played sound from it, and drops
it once the file is gone from the device. Only ids and the auto-delete
setting are kept, in a small JSON file next to tray.log; no audio.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from soundcore_diag.session import CleanupHooks

FILE_NAME = "tray-settings.json"
MAX_IDS = 500


class RecordingStore(CleanupHooks):
    def __init__(self, path: Path, log=None) -> None:
        self.path = path
        self._log = log or (lambda _line: None)
        self._lock = threading.Lock()
        self._auto_delete = True
        self._ids: list[int] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        self._auto_delete = data.get("auto_delete", True) is not False
        ids = data.get("mic_files", [])
        if isinstance(ids, list):
            self._ids = [item for item in ids if isinstance(item, int) and 0 < item < 2**32][-MAX_IDS:]

    def _save(self) -> None:
        data = {"auto_delete": self._auto_delete, "mic_files": self._ids}
        try:
            self.path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    def enabled(self) -> bool:
        with self._lock:
            return self._auto_delete

    def set_enabled(self, value: bool) -> None:
        with self._lock:
            self._auto_delete = bool(value)
            self._save()

    def pending(self) -> list[int]:
        with self._lock:
            return list(self._ids)

    def streamed(self, file_id: int) -> None:
        with self._lock:
            if file_id in self._ids:
                return
            self._ids = (self._ids + [file_id])[-MAX_IDS:]
            self._save()
            count = len(self._ids)
        self._log(f"mic recording noted, waiting to delete={count}")

    def gone(self, file_ids: set[int]) -> None:
        with self._lock:
            kept = [item for item in self._ids if item not in file_ids]
            removed = len(self._ids) - len(kept)
            if removed:
                self._ids = kept
                self._save()
        if removed:
            self._log(f"mic recordings deleted from the bean={removed} still waiting={len(kept)}")

    def forget_missing(self, present: set[int]) -> None:
        """Drop ids the device no longer has, e.g. deleted by the phone app.
        present must include the open file, which may not be listed yet."""
        with self._lock:
            kept = [item for item in self._ids if item in present]
            if kept != self._ids:
                self._ids = kept
                self._save()
