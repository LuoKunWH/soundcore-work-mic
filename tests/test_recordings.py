from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from soundcore_diag import tray_model as model
from soundcore_diag.protocol import Recording
from soundcore_diag.recording_store import RecordingStore


class RecordingStoreTests(unittest.TestCase):
    def test_remembers_streamed_files_until_gone(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            store = RecordingStore(path)
            self.assertTrue(store.enabled())
            store.streamed(7)
            store.streamed(7)
            store.streamed(9)
            again = RecordingStore(path)
            self.assertEqual(again.pending(), [7, 9])
            again.gone({7})
            again.set_enabled(False)
            last = RecordingStore(path)
            self.assertEqual(last.pending(), [9])
            self.assertFalse(last.enabled())

    def test_forgets_files_the_device_no_longer_has(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = RecordingStore(Path(folder) / "settings.json")
            for file_id in (1, 2, 3):
                store.streamed(file_id)
            store.forget_missing({2, 3, 50})
            self.assertEqual(store.pending(), [2, 3])

    def test_ignores_a_broken_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"auto_delete": "x", "mic_files": [1, "2", -3, 4]}', encoding="utf-8")
            store = RecordingStore(path)
            self.assertEqual(store.pending(), [1, 4])
            self.assertTrue(store.enabled())
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(RecordingStore(path).pending(), [])


class RecordingRowsTests(unittest.TestCase):
    def test_rows_are_newest_first_and_mark_mic_and_open_files(self) -> None:
        now = time.mktime((2026, 11, 19, 12, 0, 0, 0, 0, -1))
        today = int(time.mktime((2026, 11, 19, 9, 5, 0, 0, 0, -1)))
        earlier = int(time.mktime((2026, 11, 2, 18, 30, 0, 0, 0, -1)))
        rows = model.recording_rows(
            [Recording(earlier, 3_723_000), Recording(today, 42_000)], today + 600, [today], now
        )
        self.assertEqual([row.file_id for row in rows], [today + 600, today, earlier])
        self.assertTrue(rows[0].open and rows[0].length == "录音中")
        self.assertEqual((rows[1].when, rows[1].length, rows[1].mic), ("今天 09:05", "0:42", True))
        self.assertEqual((rows[2].when, rows[2].length, rows[2].mic), ("11-02 18:30", "1:02:03", False))
        self.assertEqual(model.format_start(5), "时间未知")

    def test_totals_and_prompts(self) -> None:
        rows = model.recording_rows([Recording(1, 30_000), Recording(2, 5_400_000)], 0, [1])
        self.assertEqual(model.total_label(rows), "2 条，共 1 小时 30 分钟")
        self.assertEqual(model.total_label([]), "豆里没有录音")
        prompt = model.delete_prompt(rows, everything=True)
        self.assertIn("其中 1 条不是当麦克风时录的", prompt)
        self.assertNotIn("不是当麦克风", model.delete_prompt(rows[1:], everything=False))
        self.assertEqual(model.delete_outcome(3, 3, 4), "已删除 3 条，豆里还剩 4 条。")
        self.assertIn("没删掉", model.delete_outcome(3, 1, 6))
        self.assertIn("固件不支持删除", model.delete_outcome(2, 0, 9))


if __name__ == "__main__":
    unittest.main()
