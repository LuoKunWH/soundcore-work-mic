"""System-tray starter for the soundcore Work microphone bridge.

Start and stop the bridge from the tray. The bridge does not change the
system default playback or recording devices; the default recording device
switches to the bean when sound starts flowing, back to the system
microphone when the bridge ends, and when the user picks 「录音豆」 or
「系统麦克风」 in the panel.
The recordings the bean made while it served as a microphone are deleted
from the bean after each one ends (if 「停后删录音」 is on), and the cleanup
window lists and deletes recordings on request, after a confirmation.
It never prints Bluetooth addresses in the user-facing notifications.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import sys
import threading
import time
import traceback
from pathlib import Path

from soundcore_diag import tray_model as model
from soundcore_diag.recording_store import FILE_NAME, RecordingStore
from soundcore_diag.tray_model import TITLE

WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_STATUS = WM_APP + 2
WM_DONE = WM_APP + 3
WM_RECORDINGS = WM_APP + 4
TRAY_CLICK_GUARD_SEC = 0.4
ID_START = 1001
ID_STOP = 1002
ID_EXIT = 1003
MUTEX_NAME = "Local\\KunSoundcoreWorkMicTray"
SOUND_SETTINGS = "ms-settings:sound"

_ICON_FILES = {
    "idle": "tray-idle.ico",
    "connect": "tray-connect.ico",
    "wait": "tray-wait.ico",
    "run": "tray-run.ico",
}


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


class TrayApp:
    def __init__(self) -> None:
        from soundcore_diag import tray_ui, tray_win32

        self.w = tray_win32
        self.ui = tray_ui
        self.hwnd = None
        self.mutex = None
        self.nid = None
        self.state = "idle"
        self.notice: model.Notice | None = None
        self.run_started = 0.0
        self.stop_flag = False
        self.worker: threading.Thread | None = None
        self.pending: list[str] = []
        self.lock = threading.Lock()
        self._toast = None
        self._menu_open = False
        self._open_menu = None
        self._ignore_tray_until = 0.0
        self._logger = self._make_logger()
        self.icons: dict[str, int] = {}
        self.mics = None
        self._system_mic = ""
        self.store = RecordingStore(_root() / FILE_NAME, log=self._log)
        self.rec_window = None
        self.rec_busy = False
        self.rec_status = ""
        self.rec_result = None
        self.rec_asked = 0
        self._rec_done = None
        self.wndproc = tray_win32.WNDPROCTYPE(self._wndproc)

    @staticmethod
    def _make_logger() -> logging.Logger:
        logger = logging.getLogger("soundcore_diag.tray")
        if not logger.handlers:
            try:
                handler = logging.FileHandler(_root() / "tray.log", encoding="utf-8", delay=True)
                handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
                logger.addHandler(handler)
            except OSError:
                logger.addHandler(logging.NullHandler())
            logger.setLevel(logging.INFO)
            logger.propagate = False
        return logger

    def _log(self, line: str) -> None:
        try:
            self._logger.info(line)
        except Exception:
            pass

    def _load_icons(self) -> None:
        w = self.w
        size = w.user32.GetSystemMetrics(w.SM_CXSMICON) or 16
        for tone, name in _ICON_FILES.items():
            path = _root() / "tray_icons" / name
            handle = None
            if path.is_file():
                handle = w.user32.LoadImageW(None, str(path), w.IMAGE_ICON, size, size, w.LR_LOADFROMFILE)
            if not handle:
                handle = w.user32.LoadIconW(None, ctypes.c_void_p(w.IDI_APPLICATION))
            self.icons[tone] = handle

    def already_running(self) -> bool:
        self.mutex = self.w.kernel32.CreateMutexW(None, True, MUTEX_NAME)
        return self.w.kernel32.GetLastError() == self.w.ERROR_ALREADY_EXISTS

    def run(self) -> int:
        w = self.w
        w.enable_dpi_awareness()
        if self.already_running():
            w.user32.MessageBoxW(
                None,
                f"{TITLE}已经在运行了，请在任务栏右下角找到它的图标。\n\n"
                "如果刚更新过程序，请先点图标，在面板里点「退出」，再重新启动，新版本才会生效。",
                TITLE,
                0x40,
            )
            return 0
        from soundcore_diag import version

        self._log(f"start {version.label()}")
        self._load_icons()
        hinst = w.kernel32.GetModuleHandleW(None)
        cls = w.WNDCLASSEXW()
        cls.cbSize = ctypes.sizeof(w.WNDCLASSEXW)
        cls.lpfnWndProc = self.wndproc
        cls.hInstance = hinst
        cls.hIcon = self.icons["idle"]
        cls.lpszClassName = "KunSoundcoreWorkMicTrayWindow"
        if not w.user32.RegisterClassExW(ctypes.byref(cls)):
            w.user32.MessageBoxW(None, "无法注册托盘窗口。", TITLE, 0x10)
            return 2
        # A real hidden top-level window (not a message-only one) owns the
        # tray icon, so the panel and the cards have a proper owner.
        self.hwnd = w.user32.CreateWindowExW(
            w.WS_EX_TOOLWINDOW, cls.lpszClassName, TITLE, w.WS_POPUP, 0, 0, 0, 0, None, None, hinst, None
        )
        if not self.hwnd:
            w.user32.MessageBoxW(None, "无法创建托盘窗口。", TITLE, 0x10)
            return 2
        w.user32.ShowWindow(self.hwnd, w.SW_HIDE)
        self._add_icon()
        self._show_toast(model.STARTED)
        msg = w.MSG()
        while w.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            w.user32.TranslateMessage(ctypes.byref(msg))
            w.user32.DispatchMessageW(ctypes.byref(msg))
        return 0

    def _add_icon(self) -> None:
        w = self.w
        self.nid = w.NOTIFYICONDATAW()
        self.nid.cbSize = ctypes.sizeof(w.NOTIFYICONDATAW)
        self.nid.hWnd = self.hwnd
        self.nid.uID = 1
        self.nid.uFlags = w.NIF_MESSAGE | w.NIF_ICON | w.NIF_TIP | w.NIF_SHOWTIP
        self.nid.uCallbackMessage = WM_TRAY
        self.nid.hIcon = self.icons["idle"]
        self.nid.szTip = model.tooltip("idle")
        if not w.shell32.Shell_NotifyIconW(w.NIM_ADD, ctypes.byref(self.nid)):
            raise RuntimeError("无法创建托盘图标")
        self.nid.uVersion = w.NOTIFYICON_VERSION_4
        w.shell32.Shell_NotifyIconW(w.NIM_SETVERSION, ctypes.byref(self.nid))

    def _icon_rect(self):
        """Screen rectangle of the tray icon, or None if the shell won't say."""
        w = self.w
        ident = w.NOTIFYICONIDENTIFIER()
        ident.cbSize = ctypes.sizeof(w.NOTIFYICONIDENTIFIER)
        ident.hWnd = self.hwnd
        ident.uID = 1
        rect = w.RECT()
        try:
            if w.shell32.Shell_NotifyIconGetRect(ctypes.byref(ident), ctypes.byref(rect)) == 0:
                if rect.right > rect.left and rect.bottom > rect.top:
                    return rect
        except OSError:
            pass
        return None

    def _refresh(self) -> None:
        """Bring the tray icon, the tooltip and an open panel in line with the state."""
        if self.nid is not None:
            w = self.w
            tone = model.state_view(self.state).tone
            self.nid.hIcon = self.icons.get(tone) or self.icons["idle"]
            self.nid.szTip = model.tooltip(self.state)[:127]
            self.nid.uFlags = w.NIF_MESSAGE | w.NIF_ICON | w.NIF_TIP | w.NIF_SHOWTIP
            w.shell32.Shell_NotifyIconW(w.NIM_MODIFY, ctypes.byref(self.nid))
        panel = self._open_menu
        if panel is not None:
            panel.refresh()

    def panel_model(self):
        elapsed = ""
        if self.state == "running" and self.run_started:
            elapsed = model.format_elapsed(time.monotonic() - self.run_started)
        mics = self.mics
        auto = self.store.enabled()
        if mics is None:
            return self.ui.PanelModel(self.state, self.notice, elapsed, auto_clean=auto)
        options = (mics.bean is not None, mics.system(self._system_mic) is not None)
        return self.ui.PanelModel(self.state, self.notice, elapsed, mics.current, options, auto)

    def _read_mics(self) -> None:
        from soundcore_diag import mic_switch

        self.mics = mic_switch.read()
        if self.mics is not None and self.mics.current == "system":
            self._system_mic = self.mics.default_id

    def _switch_mic(self, target: str, manual: bool = True) -> None:
        """Make the bean (CABLE Output) or the system microphone the default.

        A failed switch opens the sound settings only when the user asked
        for it; the automatic switches just log it.
        """
        from soundcore_diag import mic_switch

        self._read_mics()
        mics = self.mics
        if mics is None or mics.current == target:
            return
        endpoint = mics.bean if target == "bean" else mics.system(self._system_mic)
        if endpoint is None:
            return
        ok = mic_switch.set_default(endpoint.id)
        self._log(f"mic switch target={target} manual={manual} ok={ok}")
        self._read_mics()
        if not ok and manual:
            self.w.shell32.ShellExecuteW(None, "open", SOUND_SETTINGS, None, None, 1)

    def _show_toast(self, notice: model.Notice) -> None:
        # While the panel is open it already shows the same thing.
        if not notice.toast or not notice.title or self._open_menu is not None:
            return
        if self._toast is None:
            self._toast = self.ui.ToastWindow(self)
        self._toast.show(notice, self._icon_rect())

    def _hide_toast(self) -> None:
        if self._toast is not None:
            self._toast.close()

    def _set_state(self, state: str) -> None:
        self.state = state
        if state == "running":
            self.run_started = time.monotonic()
        self._refresh()
        self._refresh_recordings()

    def _post_status(self, message: str) -> None:
        with self.lock:
            self.pending.append(message)
        self.w.user32.PostMessageW(self.hwnd, WM_STATUS, 0, 0)

    def _on_status(self, message: str) -> None:
        # Called on the bridge thread; the window thread does the rest.
        self._post_status(message)

    def _drain_status(self) -> None:
        with self.lock:
            items = list(self.pending)
            self.pending.clear()
        last = None
        for message in items:
            notice = model.interpret(message)
            self._log(f"status state={self.state} next={notice.state} tone={notice.tone} {message}")
            if self.state != "stopping":
                if notice.state == "running":
                    if self.state != "running":
                        self.run_started = time.monotonic()
                        self._switch_mic("bean", manual=False)
                    self.state = "running"
                elif notice.state == "waiting":
                    self.state = "waiting"
                elif notice.state == "starting" and self.state not in {"waiting", "running"}:
                    self.state = "starting"
            if notice.title:
                last = notice
        if last is not None:
            if last.sticky:
                self.notice = last
            self._show_toast(last)
        self._refresh()

    def _on_done(self, code: int) -> None:
        self._log(f"done code={code}")
        self.w.user32.PostMessageW(self.hwnd, WM_DONE, code & 0xFFFFFFFF, 0)

    def _set_auto_clean(self, value: bool) -> None:
        self.store.set_enabled(value)
        self._log(f"auto clean={'on' if value else 'off'}")

    def recordings_model(self):
        result = self.rec_result
        rows = ()
        if result is not None and result.listed:
            rows = tuple(model.recording_rows(result.recordings, result.open_id, self.store.pending()))
        blocked = ""
        if self.state != "idle":
            blocked = "正在桥接。先在面板里点「停止桥接」，再来整理录音。"
        return self.ui.RecordingsModel(
            rows, result is not None and result.listed, self.rec_busy, blocked, self.rec_status
        )

    def _open_recordings(self) -> None:
        if self.rec_window is None:
            self.rec_window = self.ui.RecordingsWindow(self)
        self.rec_window.show()
        if self.rec_result is None or not self.rec_result.listed:
            self.recordings_refresh()
        else:
            self.rec_window.refresh()

    def recordings_refresh(self) -> None:
        self._recordings_job([])

    def recordings_delete(self, file_ids: list[int]) -> None:
        self._recordings_job(file_ids)

    def _recordings_job(self, file_ids: list[int]) -> None:
        if self.rec_busy or self.state != "idle":
            return
        self.rec_busy = True
        self.rec_asked = len(file_ids)
        self.rec_status = "正在连接录音豆…"
        self._log(f"recordings job delete={len(file_ids)}")
        self._refresh_recordings()

        def on_status(message: str) -> None:
            self.rec_status = message
            self.w.user32.PostMessageW(self.hwnd, WM_RECORDINGS, 0, 0)

        def work() -> None:
            from soundcore_diag.live import run_recordings

            result = None
            try:
                result = asyncio.run(run_recordings(file_ids, stop=lambda: self.stop_flag, on_status=on_status))
            except Exception:
                self._log("recordings exception\n" + traceback.format_exc())
            self._rec_done = result
            self.w.user32.PostMessageW(self.hwnd, WM_RECORDINGS, 1, 0)

        threading.Thread(target=work, name="soundcore-recordings", daemon=True).start()

    def _recordings_finished(self) -> None:
        result = self._rec_done
        self._rec_done = None
        self.rec_busy = False
        asked = self.rec_asked
        self.rec_asked = 0
        if result is None:
            if not self.rec_status or self.rec_status.startswith("正在"):
                self.rec_status = "没有连上录音豆。请靠近电脑、断开手机上的连接后点「刷新」。"
        elif not result.listed:
            self._log(f"recordings failed reason={result.stop_reason}")
            self.rec_status = "录音豆没有回应，读不到录音列表。请点「刷新」再试一次。"
            if result.deleted:
                self.store.gone(result.deleted)
        else:
            present = {item.file_id for item in result.recordings} | {result.open_id}
            self.store.gone(result.deleted)
            self.store.forget_missing(present)
            self.rec_result = result
            left = sum(1 for item in result.recordings if item.file_id != result.open_id)
            self._log(f"recordings listed={len(result.recordings)} asked={asked} deleted={len(result.deleted)}")
            self.rec_status = model.delete_outcome(asked, len(result.deleted), left) if asked else ""
        self._refresh_recordings()

    def _refresh_recordings(self) -> None:
        window = self.rec_window
        if window is not None and window.is_shown:
            window.refresh()

    def _start(self) -> None:
        if self.rec_busy:
            self._show_toast(model.Notice("connect", "正在整理录音", "等这一步做完再开始桥接。", toast=True))
            return
        if self.state != "idle":
            self._show_toast(model.BUSY)
            return
        self.stop_flag = False
        self.notice = None
        self._hide_toast()
        self._log("user start")
        self._set_state("starting")
        self.worker = threading.Thread(target=self._worker, name="soundcore-bridge", daemon=True)
        self.worker.start()

    def _request_stop(self) -> None:
        if self.state == "idle":
            self._show_toast(model.NOT_RUNNING)
            return
        self.stop_flag = True
        self._hide_toast()
        self._set_state("stopping")

    def _worker(self) -> None:
        from soundcore_diag.live import run_cable_session

        def stop() -> bool:
            return self.stop_flag

        try:
            self._log("worker start")
            code = asyncio.run(
                run_cable_session(
                    stop=stop,
                    on_status=self._on_status,
                    cleanup=self.store,
                    on_log=self._log,
                )
            )
            self._log(f"worker return {code}")
        except Exception:
            self._log("worker exception\n" + traceback.format_exc())
            self._post_status(model.CRASHED)
            code = 2
        self._on_done(code)

    def _finish(self, code: int) -> None:
        self._log(f"finish code={code} state={self.state}")
        self.stop_flag = False
        self.worker = None
        # Show any last real status first, then return the icon to idle.
        self._drain_status()
        self._switch_mic("system", manual=False)
        self._set_state("idle")

    def _bring_to_foreground(self, hwnd=None) -> None:
        w = self.w
        target = hwnd or self.hwnd
        fg = w.user32.GetForegroundWindow()
        attached = False
        fg_tid = 0
        if fg and fg != target:
            fg_tid = w.user32.GetWindowThreadProcessId(fg, None)
            our_tid = w.kernel32.GetCurrentThreadId()
            if fg_tid and fg_tid != our_tid:
                attached = bool(w.user32.AttachThreadInput(our_tid, fg_tid, True))
        w.user32.SetForegroundWindow(target)
        if attached and fg_tid:
            w.user32.AttachThreadInput(w.kernel32.GetCurrentThreadId(), fg_tid, False)

    def _popup(self) -> None:
        now = time.monotonic()
        if now < self._ignore_tray_until:
            return
        if self._menu_open:
            # A later click on the tray icon dismisses the open panel.
            # Ignore trailing events from the same click that opened it
            # (NIN_SELECT, button-up, and context-menu can arrive together).
            panel = self._open_menu
            if panel is not None and panel._can_dismiss:
                self._log("popup toggle-close")
                panel._close()
                self._ignore_tray_until = time.monotonic() + TRAY_CLICK_GUARD_SEC
            return
        self._menu_open = True
        # Hold off additional tray events from this same click.
        self._ignore_tray_until = now + TRAY_CLICK_GUARD_SEC
        cmd = ""
        try:
            self._hide_toast()
            self._read_mics()
            pt = self.w.POINT()
            self.w.user32.GetCursorPos(ctypes.byref(pt))
            panel = self.ui.PanelWindow(self)
            self._open_menu = panel
            self._log("popup open")
            cmd = panel.show(self._icon_rect(), pt)
            self._log(f"popup close cmd={cmd}")
        finally:
            self._open_menu = None
            self._menu_open = False
        if cmd == "settings":
            self.w.shell32.ShellExecuteW(None, "open", SOUND_SETTINGS, None, None, 1)
        elif cmd == "recordings":
            self._open_recordings()
        elif cmd == "exit":
            self._exit()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        w = self.w
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event in (
                w.WM_RBUTTONUP,
                w.WM_LBUTTONUP,
                w.WM_LBUTTONDBLCLK,
                w.WM_CONTEXTMENU,
                w.NIN_SELECT,
                w.NIN_KEYSELECT,
            ):
                self._popup()
                return 0
        elif msg == w.WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == ID_START:
                self._start()
            elif cmd == ID_STOP:
                self._request_stop()
            elif cmd == ID_EXIT:
                self._exit()
            return 0
        elif msg == WM_STATUS:
            self._drain_status()
            return 0
        elif msg == WM_DONE:
            self._finish(wparam)
            return 0
        elif msg == WM_RECORDINGS:
            if wparam == 1:
                self._recordings_finished()
            else:
                self._refresh_recordings()
            return 0
        elif msg == w.WM_DESTROY:
            if self.nid is not None:
                w.shell32.Shell_NotifyIconW(w.NIM_DELETE, ctypes.byref(self.nid))
            w.user32.PostQuitMessage(0)
            return 0
        return w.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _exit(self) -> None:
        w = self.w
        if self.state != "idle":
            self.stop_flag = True
            self._set_state("stopping")
            worker = self.worker
            if worker is not None:
                worker.join(8)
            self._switch_mic("system", manual=False)
        if self.rec_window is not None:
            self.rec_window.close()
            self.rec_window = None
        if self._toast is not None:
            self._toast.close()
            self._toast = None
        if self.nid is not None:
            w.shell32.Shell_NotifyIconW(w.NIM_DELETE, ctypes.byref(self.nid))
            self.nid = None
        w.user32.DestroyWindow(self.hwnd)


def main(argv: list[str] | None = None) -> int:
    del argv
    if sys.platform != "win32":
        print("这个托盘程序只能在 Windows 上运行。")
        return 2
    return TrayApp().run()


if __name__ == "__main__":
    raise SystemExit(main())
