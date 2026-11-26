"""Cable endpoint selection without PortAudio or VB-CABLE."""

from __future__ import annotations

import ast
import time
import unittest
from pathlib import Path

from soundcore_diag.cable import (
    CableSink,
    CableUnavailable,
    Pcm16Resampler,
    PcmByteQueue,
    expand_pcm,
    open_cable_input,
    pcm_peak,
)
from soundcore_diag.selftest import _check_cable


def _tone(sample: int, count: int) -> bytes:
    return int(sample).to_bytes(2, "little", signed=True) * count


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
        # Playback must not block the Bluetooth thread inside PortAudio.
        sink = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CableSink")
        write = next(node for node in sink.body if isinstance(node, ast.FunctionDef) and node.name == "write")
        called = [
            node.func.attr
            for node in ast.walk(write)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        self.assertNotIn("write", called)

    def test_resample_keeps_level(self) -> None:
        tone = _tone(1000, 160)
        self.assertEqual(pcm_peak(tone), 1000)
        self.assertEqual(pcm_peak(bytes(320)), 0)
        up = Pcm16Resampler(16000, 48000)
        played = up.feed(tone)
        self.assertEqual(pcm_peak(played), 1000)
        self.assertEqual(len(played), len(tone) * 3)
        again = Pcm16Resampler(16000, 48000)
        self.assertEqual(again.feed(tone[: len(tone) // 2]) + again.feed(tone[len(tone) // 2 :]), played)
        self.assertEqual(pcm_peak(Pcm16Resampler(16000, 48000).feed(bytes(320))), 0)
        self.assertEqual(Pcm16Resampler(16000, 16000).feed(tone), tone)
        stereo = expand_pcm(played, 2)
        self.assertEqual(pcm_peak(stereo), 1000)
        self.assertEqual(len(stereo), len(played) * 2)

    def test_queue_pads_and_drops_whole_frames(self) -> None:
        queue = PcmByteQueue(8)
        frame = b"\x01\x00\x01\x00"
        queue.push(frame * 4, frame_bytes=4)
        _pulls, dropped, queued = queue.snapshot()
        self.assertEqual(queued, 8)
        self.assertEqual(dropped, 8)
        self.assertEqual(dropped % 4, 0)
        got = queue.pull(12)
        self.assertEqual(got, frame * 2 + bytes(4))
        self.assertEqual(queue.snapshot()[0], 1)

    def test_stale_callback_fails_the_write_instead_of_hanging(self) -> None:
        sink = CableSink.__new__(CableSink)
        sink._log = None
        sink._resampler = None
        sink.channels = 2
        sink.samplerate = 48000
        sink._frame_bytes = 4
        sink._queue = PcmByteQueue(48000 * 4)
        sink._dead = False
        sink._underruns = 0
        sink._opened_at = time.monotonic() - 5
        sink._pulls_seen = 0
        sink._pulls_seen_at = sink._opened_at
        sink._last_log = 0.0
        sink.writes = 0
        sink.peak = 0
        sink.nonzero_writes = 0
        sink.name = "CABLE Input"
        sink.hostapi = "Windows WASAPI"
        logged: list[str] = []
        sink._log = logged.append
        with self.assertRaises(CableUnavailable):
            sink.write(_tone(2000, 32))
        self.assertEqual(sink.peak, 2000)
        self.assertEqual(sink.nonzero_writes, 1)
        self.assertTrue(any(line.startswith("cable level ") and "peak=2000" in line for line in logged))
        self.assertTrue(any(line.startswith("cable error ") for line in logged))
        # A callback that is actually pulling accepts the same PCM.
        sink._queue.pull(64)
        sink._pulls_seen = -1
        sink.write(_tone(2000, 32))
        self.assertGreater(sink._queue.snapshot()[2], 0)


if __name__ == "__main__":
    unittest.main()
