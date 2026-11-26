"""Tray wording and state mapping. These tests need no Windows and no Bluetooth."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from soundcore_diag import tray_model as model
from soundcore_diag.cable import MISSING_TEXT

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "src" / "soundcore_diag" / "live.py"


def _live_status_texts() -> list[str]:
    """Every literal sentence the bridge passes to status()."""
    tree = ast.parse(LIVE.read_text(encoding="utf-8"))
    texts = []
    for func in ast.walk(tree):
        if isinstance(func, ast.AsyncFunctionDef) and func.name in ("run_cable_session", "_connect_nearest"):
            for node in ast.walk(func):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "status" and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        texts.append(arg.value)
                    elif isinstance(arg, ast.JoinedStr):
                        texts.append(
                            "".join(
                                part.value if isinstance(part, ast.Constant) else "链路断开" for part in arg.values
                            )
                        )
    return texts


class TrayModelTests(unittest.TestCase):
    def test_every_bridge_status_has_its_own_wording(self) -> None:
        texts = _live_status_texts()
        self.assertGreater(len(texts), 15)
        for text in texts:
            notice = model.interpret(text)
            self.assertNotIn(notice.title, ("提示", "桥接已停止"), text)

    def test_states_follow_the_bridge(self) -> None:
        cases = {
            "正在打开虚拟声卡…": "starting",
            "虚拟声卡已打开。请在要用的软件里把麦克风选成 CABLE Output。": "starting",
            "正在扫描录音豆…": "starting",
            "已找到录音豆，正在连接…": "starting",
            "已连上。请按下录音豆上的录音键，灯变色后对着它说话。": "waiting",
            "正在传输声音。请在要用的软件里把麦克风选成 CABLE Output。": "running",
            "录音已暂停，连接还在。再按一下录音豆上的录音键，就会接着传声。": "waiting",
            "已取消，未连接。": None,
            "桥接已停止。请再按一下录音豆上的键，把豆上的录音停掉。": None,
            "没有找到录音豆。请把它靠近电脑，并先断开手机上的连接后再试。": None,
            "已连接但没有收到声音。请确认豆上已经开始录音后再试。": None,
            "连接或传输失败，已停止。没有改试其他认证或协议。": None,
        }
        for text, state in cases.items():
            self.assertEqual(model.interpret(text).state, state, text)

    def test_failures_are_errors_and_stay_in_the_panel(self) -> None:
        for text in (
            "没有找到录音豆。请把它靠近电脑，并先断开手机上的连接后再试。",
            "没有等到录音开始。若豆已经在录音，请先按停再按一次开始。",
            "已连接但没有收到声音。请确认豆上已经开始录音后再试。",
            "连接或传输失败，已停止。没有改试其他认证或协议。",
            "设备特征不匹配，已断开。未发送录音控制。",
            "解码器不可用，未打开蓝牙。",
            "桥接已停止（链路断开）。请再按一下豆上的键停掉录音。",
            MISSING_TEXT,
            "找到多个标准 CABLE Input 播放端，没有自动挑选。\n" + MISSING_TEXT,
            "无法打开 CABLE Input。已尝试该播放端当前的采样率和 16000 Hz，没有修改系统默认设备。",
            "检测到 SD_ENABLE_ASIO。本程序不加载 ASIO 版 PortAudio，也没有打开声卡。",
            model.CRASHED,
            "某个没有见过的失败",
        ):
            notice = model.interpret(text)
            self.assertEqual(notice.tone, "error", text)
            self.assertTrue(notice.toast and notice.sticky and notice.title, text)

    def test_user_stop_is_a_reminder_not_an_error(self) -> None:
        notice = model.interpret("桥接已停止。请再按一下录音豆上的键，把豆上的录音停掉。")
        self.assertEqual((notice.tone, notice.title), ("idle", "已停止桥接"))
        self.assertTrue(notice.toast and notice.sticky)
        self.assertIn("再按一下", notice.body)

    def test_reason_is_kept(self) -> None:
        ended = model.interpret("桥接已结束（对端结束了传输）。请再按一下豆上的键停掉录音。")
        self.assertEqual(ended.tone, "idle")
        self.assertIn("对端结束了传输", ended.body)
        broken = model.interpret("桥接已停止（链路断开）。请再按一下豆上的键停掉录音。")
        self.assertIn("链路断开", broken.body)

    def test_quiet_progress_shows_no_card(self) -> None:
        for text in ("正在扫描录音豆…", "已找到录音豆，正在连接…", "已取消，未连接。", "已取消，已断开。"):
            self.assertFalse(model.interpret(text).toast, text)

    def test_every_state_and_tone_can_be_drawn(self) -> None:
        for state in ("idle", "starting", "waiting", "running", "stopping"):
            view = model.state_view(state)
            self.assertIn(view.tone, model.TONES)
            self.assertIn(view.tone, model.GLYPHS)
            self.assertLessEqual(view.step, len(model.STEPS))
            self.assertLess(len(model.tooltip(state)), 128)
        self.assertEqual(model.state_view("unknown"), model.state_view("idle"))
        self.assertIn("error", model.GLYPHS)

    def test_elapsed(self) -> None:
        self.assertEqual(model.format_elapsed(0), "00:00")
        self.assertEqual(model.format_elapsed(75.9), "01:15")
        self.assertEqual(model.format_elapsed(3725), "1:02:05")
        self.assertEqual(model.format_elapsed(-3), "00:00")


if __name__ == "__main__":
    unittest.main()
