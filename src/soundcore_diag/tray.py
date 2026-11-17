"""System-tray starter for the soundcore Work microphone bridge.

Start and stop the bridge from the tray. This program does not change the
system default playback or recording devices, and it never prints Bluetooth
addresses in the user-facing notifications.
"""

from __future__ import annotations

import asyncio
import ctypes
import sys
import time
import traceback
import threading
from ctypes import wintypes
from pathlib import Path

WM_DESTROY = 0x0002
WM_NULL = 0x0000
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_ACTIVATE = 0x0006
WM_SETCURSOR = 0x0020
WM_MOUSEACTIVATE = 0x0021
WM_KEYDOWN = 0x0100
WM_COMMAND = 0x0111
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_MOUSELEAVE = 0x02A3
WM_PRINTCLIENT = 0x0318
VK_ESCAPE = 0x1B
VK_RETURN = 0x0D
VK_UP = 0x26
VK_DOWN = 0x28
WA_INACTIVE = 0
CS_VREDRAW = 0x0001
CS_HREDRAW = 0x0002
CS_DROPSHADOW = 0x00020000
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
SW_SHOWNA = 8
SW_SHOW = 5
SW_SHOWNOACTIVATE = 4
WM_TIMER = 0x0113
DT_WORDBREAK = 0x0010
DT_CALCRECT = 0x0400
DT_NOPREFIX = 0x0800
DT_CENTER = 0x0001
IDC_ARROW = 32512
DT_LEFT = 0x0000
DT_VCENTER = 0x0004
DT_SINGLELINE = 0x0020
DT_END_ELLIPSIS = 0x8000
TRANSPARENT = 1
FW_NORMAL = 400
DEFAULT_CHARSET = 1
CLEARTYPE_QUALITY = 5
PS_SOLID = 0
MONITOR_DEFAULTTONEAREST = 2
TME_LEAVE = 0x00000002
WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_STATUS = WM_APP + 2
WM_DONE = WM_APP + 3
# NOTIFYICON_VERSION_4 uses LOWORD(lParam) for the event, and
# often sends NIN_SELECT / WM_CONTEXTMENU instead of button-up.
NIN_SELECT = 0x0400
NIN_KEYSELECT = 0x0401
WM_CONTEXTMENU = 0x007B
WM_LBUTTONDBLCLK = 0x0203
WM_MENU_ENABLE_DISMISS = WM_APP + 10
TRAY_CLICK_GUARD_SEC = 0.4

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETVERSION = 4
NOTIFYICON_VERSION_4 = 4
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NIIF_INFO = 0x00000001
NIIF_WARNING = 0x00000002
NIIF_ERROR = 0x00000003
NIIF_NOSOUND = 0x00000010

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_GRAYED = 0x00000001
TPM_RIGHTBUTTON = 0x0002
TPM_BOTTOMALIGN = 0x0020
TPM_RETURNCMD = 0x0100
IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
CW_USEDEFAULT = 0x80000000
WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x00000080
SW_HIDE = 0
ERROR_ALREADY_EXISTS = 183
ID_START = 1001
ID_STOP = 1002
ID_EXIT = 1003
MUTEX_NAME = "Local\\KunSoundcoreWorkMicTray"
TITLE = "录音豆麦克风"

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

WNDPROCTYPE = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROCTYPE),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", wintypes.BYTE * 32),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("hwndTrack", wintypes.HWND),
        ("dwHoverTime", wintypes.DWORD),
    ]



user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    ctypes.c_void_p,
]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.DestroyMenu.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

gdi32 = ctypes.windll.gdi32

user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.restype = wintypes.BOOL
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), wintypes.HBRUSH]
user32.FillRect.restype = ctypes.c_int
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(RECT), wintypes.UINT]
user32.DrawTextW.restype = ctypes.c_int
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
user32.InvalidateRect.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
user32.TrackMouseEvent.restype = wintypes.BOOL
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.UpdateWindow.argtypes = [wintypes.HWND]
user32.UpdateWindow.restype = wintypes.BOOL

user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.KillTimer.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
try:
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT
except AttributeError:
    pass

gdi32.CreateFontW.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
]
gdi32.CreateFontW.restype = wintypes.HGDIOBJ
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
gdi32.CreatePen.restype = wintypes.HANDLE
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
gdi32.SetTextColor.restype = wintypes.COLORREF
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetBkMode.restype = ctypes.c_int
gdi32.MoveToEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
gdi32.MoveToEx.restype = wintypes.BOOL
gdi32.LineTo.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.LineTo.restype = wintypes.BOOL


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


def _icon_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tray_icons"


def _load_icon(name: str) -> int:
    path = _icon_dir() / name
    handle = 0
    if path.is_file():
        handle = user32.LoadImageW(
            None,
            str(path),
            IMAGE_ICON,
            0,
            0,
            LR_LOADFROMFILE | LR_DEFAULTSIZE,
        )
    if not handle:
        handle = user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
    return handle



class TrayMenu:
    """Owner-drawn tray menu with dark text on a light background."""

    CLASS_NAME = "KunSoundcoreWorkMicTrayMenu"
    _class_registered = False
    _wndproc_ref = None

    # COLORREF is 0x00BBGGRR
    COLOR_BG = 0x00FFFFFF
    COLOR_HOVER = 0x00F3F1EE
    COLOR_TEXT = 0x001F1B1B
    COLOR_DISABLED = 0x00A6A09A
    COLOR_SEP = 0x00E6E2E2
    COLOR_BORDER = 0x00D8D5D5

    def __init__(self, owner: "TrayApp") -> None:
        self.owner = owner
        self.hwnd = None
        self.cmd = 0
        self.hover = -1
        self.font = None
        self.brushes: list = []
        self.items: list[dict] = []
        self.tracking_leave = False
        self._can_dismiss = False
        self.dpi = 96
        self.wndproc = WNDPROCTYPE(self._wndproc)

    def _scale(self, px: int) -> int:
        return max(1, int(round(px * self.dpi / 96.0)))

    def _dpi_for(self) -> int:
        hwnd = self.owner.hwnd
        getter = getattr(user32, "GetDpiForWindow", None)
        if getter and hwnd:
            try:
                value = int(getter(hwnd) or 0)
                if value:
                    return value
            except OSError:
                pass
        return 96

    def _build_items(self) -> None:
        start_on = self.owner.state == "idle"
        stop_on = self.owner.state != "idle"
        self.items = [
            {"kind": "item", "id": ID_START, "text": "开始桥接", "enabled": start_on, "rect": RECT()},
            {"kind": "item", "id": ID_STOP, "text": "停止桥接", "enabled": stop_on, "rect": RECT()},
            {"kind": "sep", "id": 0, "text": "", "enabled": False, "rect": RECT()},
            {"kind": "item", "id": ID_EXIT, "text": "退出", "enabled": True, "rect": RECT()},
        ]

    def _layout(self) -> tuple[int, int]:
        pad_x = self._scale(16)
        pad_y = self._scale(6)
        item_h = self._scale(36)
        sep_h = self._scale(9)
        width = self._scale(172)
        y = pad_y
        for item in self.items:
            if item["kind"] == "sep":
                item["rect"] = RECT(0, y, width, y + sep_h)
                y += sep_h
            else:
                item["rect"] = RECT(0, y, width, y + item_h)
                y += item_h
        y += pad_y
        return width, y

    def _register(self, hinst) -> bool:
        if TrayMenu._class_registered:
            return True
        # Keep a class-level reference so the callback is not collected.
        TrayMenu._wndproc_ref = self.wndproc
        cls = WNDCLASSEXW()
        cls.cbSize = ctypes.sizeof(WNDCLASSEXW)
        cls.style = CS_HREDRAW | CS_VREDRAW | CS_DROPSHADOW
        cls.lpfnWndProc = TrayMenu._wndproc_ref
        cls.hInstance = hinst
        cls.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        cls.hbrBackground = gdi32.CreateSolidBrush(self.COLOR_BG)
        cls.lpszClassName = self.CLASS_NAME
        if not user32.RegisterClassExW(ctypes.byref(cls)):
            # Already registered in this process is fine (error 1410).
            if kernel32.GetLastError() not in (1410, 0):
                # Still try to proceed if the class exists.
                pass
        TrayMenu._class_registered = True
        return True

    def show(self, x: int, y: int) -> int:
        self.dpi = self._dpi_for()
        self._build_items()
        width, height = self._layout()
        hinst = kernel32.GetModuleHandleW(None)
        self._register(hinst)
        self.font = gdi32.CreateFontW(
            -self._scale(14),
            0,
            0,
            0,
            FW_NORMAL,
            0,
            0,
            0,
            DEFAULT_CHARSET,
            0,
            0,
            CLEARTYPE_QUALITY,
            0,
            "Microsoft YaHei UI",
        )
        # Place the menu above the cursor, kept inside the work area.
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        mon = user32.MonitorFromPoint(POINT(x, y), MONITOR_DEFAULTTONEAREST)
        work = RECT(0, 0, 1920, 1080)
        if mon and user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            work = mi.rcWork
        pos_x = x - self._scale(24)
        pos_y = y - height - self._scale(8)
        if pos_y < work.top:
            pos_y = y + self._scale(8)
        if pos_x + width > work.right:
            pos_x = work.right - width - self._scale(4)
        if pos_x < work.left:
            pos_x = work.left + self._scale(4)
        if pos_y + height > work.bottom:
            pos_y = work.bottom - height - self._scale(4)

        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOOLWINDOW | WS_EX_TOPMOST,
            self.CLASS_NAME,
            TITLE,
            WS_POPUP,
            pos_x,
            pos_y,
            width,
            height,
            self.owner.hwnd,
            None,
            hinst,
            None,
        )
        if not self.hwnd:
            self._cleanup()
            return 0
        # Bind this instance to the window; the class wndproc is the same
        # callback object, so route via a dict of hwnd -> instance.
        _MENUS[int(self.hwnd)] = self
        self._can_dismiss = False
        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.UpdateWindow(self.hwnd)
        # HWND_TOPMOST = -1
        user32.SetWindowPos(self.hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x0043)
        self.owner._open_menu = self
        self.owner._bring_to_foreground(self.hwnd)
        # Enable click-outside dismiss only after the opening click has settled.
        user32.PostMessageW(self.hwnd, WM_MENU_ENABLE_DISMISS, 0, 0)

        msg = MSG()
        while self.hwnd and user32.IsWindow(self.hwnd):
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result == 0:  # WM_QUIT for the app
                user32.PostQuitMessage(msg.wParam)
                self._close()
                break
            if result == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        cmd = self.cmd
        self._cleanup()
        return cmd

    def _item_at(self, lx: int, ly: int) -> int:
        for index, item in enumerate(self.items):
            rc = item["rect"]
            if rc.left <= lx < rc.right and rc.top <= ly < rc.bottom:
                return index
        return -1

    def _close(self, cmd: int = 0) -> None:
        if cmd:
            self.cmd = cmd
        if getattr(self.owner, "_open_menu", None) is self:
            self.owner._open_menu = None
        hwnd = self.hwnd
        self.hwnd = None
        if hwnd and user32.IsWindow(hwnd):
            user32.DestroyWindow(hwnd)

    def _cleanup(self) -> None:
        if self.font:
            gdi32.DeleteObject(self.font)
            self.font = None
        for brush in self.brushes:
            gdi32.DeleteObject(brush)
        self.brushes = []

    def _paint(self, hwnd) -> None:
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        client = RECT()
        user32.GetClientRect(hwnd, ctypes.byref(client))
        br_bg = gdi32.CreateSolidBrush(self.COLOR_BG)
        br_hover = gdi32.CreateSolidBrush(self.COLOR_HOVER)
        user32.FillRect(hdc, ctypes.byref(client), br_bg)
        old_font = gdi32.SelectObject(hdc, self.font) if self.font else None
        gdi32.SetBkMode(hdc, TRANSPARENT)
        for index, item in enumerate(self.items):
            rc = item["rect"]
            if item["kind"] == "sep":
                mid = (rc.top + rc.bottom) // 2
                pen = gdi32.CreatePen(PS_SOLID, self._scale(1), self.COLOR_SEP)
                old_pen = gdi32.SelectObject(hdc, pen)
                inset = self._scale(12)
                gdi32.MoveToEx(hdc, inset, mid, None)
                gdi32.LineTo(hdc, rc.right - inset, mid)
                gdi32.SelectObject(hdc, old_pen)
                gdi32.DeleteObject(pen)
                continue
            if index == self.hover and item["enabled"]:
                user32.FillRect(hdc, ctypes.byref(rc), br_hover)
            color = self.COLOR_TEXT if item["enabled"] else self.COLOR_DISABLED
            gdi32.SetTextColor(hdc, color)
            text_rc = RECT(rc.left + self._scale(16), rc.top, rc.right - self._scale(12), rc.bottom)
            user32.DrawTextW(
                hdc,
                item["text"],
                -1,
                ctypes.byref(text_rc),
                DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS,
            )
        # Border
        pen = gdi32.CreatePen(PS_SOLID, self._scale(1), self.COLOR_BORDER)
        old_pen = gdi32.SelectObject(hdc, pen)
        null_brush = ctypes.windll.gdi32.GetStockObject(5)  # NULL_BRUSH
        old_br = gdi32.SelectObject(hdc, null_brush)
        # Rectangle API
        ctypes.windll.gdi32.Rectangle(hdc, client.left, client.top, client.right, client.bottom)
        gdi32.SelectObject(hdc, old_br)
        gdi32.SelectObject(hdc, old_pen)
        gdi32.DeleteObject(pen)
        gdi32.DeleteObject(br_bg)
        gdi32.DeleteObject(br_hover)
        if old_font:
            gdi32.SelectObject(hdc, old_font)
        user32.EndPaint(hwnd, ctypes.byref(ps))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        inst = _MENUS.get(int(hwnd), self)
        return inst._dispatch(hwnd, msg, wparam, lparam)

    def _dispatch(self, hwnd, msg, wparam, lparam):
        if msg == WM_PAINT or msg == WM_PRINTCLIENT:
            self._paint(hwnd)
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg in (WM_MOUSEACTIVATE,):
            return 2  # MA_ACTIVATE
        if msg == WM_MOUSEMOVE:
            lx = ctypes.c_short(lparam & 0xFFFF).value
            ly = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            index = self._item_at(lx, ly)
            if index != self.hover:
                self.hover = index
                user32.InvalidateRect(hwnd, None, True)
            if not self.tracking_leave:
                tme = TRACKMOUSEEVENT()
                tme.cbSize = ctypes.sizeof(TRACKMOUSEEVENT)
                tme.dwFlags = TME_LEAVE
                tme.hwndTrack = hwnd
                user32.TrackMouseEvent(ctypes.byref(tme))
                self.tracking_leave = True
            return 0
        if msg == WM_MOUSELEAVE:
            self.tracking_leave = False
            if self.hover != -1:
                self.hover = -1
                user32.InvalidateRect(hwnd, None, True)
            return 0
        if msg == WM_LBUTTONUP:
            lx = ctypes.c_short(lparam & 0xFFFF).value
            ly = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            index = self._item_at(lx, ly)
            if index >= 0 and self.items[index]["kind"] == "item" and self.items[index]["enabled"]:
                self._close(self.items[index]["id"])
            return 0
        if msg == WM_KEYDOWN:
            key = wparam & 0xFFFFFFFF
            if key == VK_ESCAPE:
                self._close(0)
                return 0
            if key in (VK_DOWN, VK_UP):
                enabled = [i for i, it in enumerate(self.items) if it["kind"] == "item"]
                if not enabled:
                    return 0
                if self.hover not in enabled:
                    self.hover = enabled[0] if key == VK_DOWN else enabled[-1]
                else:
                    pos = enabled.index(self.hover)
                    pos = (pos + (1 if key == VK_DOWN else -1)) % len(enabled)
                    self.hover = enabled[pos]
                user32.InvalidateRect(hwnd, None, True)
                return 0
            if key == VK_RETURN and 0 <= self.hover < len(self.items):
                item = self.items[self.hover]
                if item["kind"] == "item" and item["enabled"]:
                    self._close(item["id"])
                return 0
        if msg == WM_MENU_ENABLE_DISMISS:
            self._can_dismiss = True
            return 0
        if msg == WM_ACTIVATE:
            if (wparam & 0xFFFF) == WA_INACTIVE and self._can_dismiss:
                self._close(0)
            return 0
        if msg == WM_DESTROY:
            _MENUS.pop(int(hwnd), None)
            # Unblock the modal loop if _close wasn't used.
            if self.hwnd == hwnd:
                self.hwnd = None
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_MENUS: dict[int, TrayMenu] = {}



class TrayToast:
    """A short, always-visible status popup. Win11 often hides tray balloons."""

    CLASS_NAME = "KunSoundcoreWorkMicTrayToast"
    _class_registered = False
    _wndproc_ref = None
    _current = None

    COLOR_BG = 0x00FFFFFF
    COLOR_TEXT = 0x001F1B1B
    COLOR_BORDER = 0x00D8D5D5
    COLOR_BAR = {
        "info": 0x00488C1C,   # green
        "warn": 0x001670C9,   # amber
        "error": 0x00322CD1,  # red
    }

    def __init__(self, owner: "TrayApp") -> None:
        self.owner = owner
        self.hwnd = None
        self.font = None
        self.text = ""
        self.kind = "info"
        self.dpi = 96
        self.wndproc = WNDPROCTYPE(self._wndproc)

    def _scale(self, px: int) -> int:
        return max(1, int(round(px * self.dpi / 96.0)))

    def _dpi(self) -> int:
        getter = getattr(user32, "GetDpiForWindow", None)
        if getter and self.owner.hwnd:
            try:
                value = int(getter(self.owner.hwnd) or 0)
                if value:
                    return value
            except OSError:
                pass
        return 96

    def _register(self, hinst) -> None:
        if TrayToast._class_registered:
            return
        TrayToast._wndproc_ref = self.wndproc
        cls = WNDCLASSEXW()
        cls.cbSize = ctypes.sizeof(WNDCLASSEXW)
        cls.style = CS_HREDRAW | CS_VREDRAW | CS_DROPSHADOW
        cls.lpfnWndProc = TrayToast._wndproc_ref
        cls.hInstance = hinst
        cls.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        cls.hbrBackground = gdi32.CreateSolidBrush(self.COLOR_BG)
        cls.lpszClassName = self.CLASS_NAME
        user32.RegisterClassExW(ctypes.byref(cls))
        TrayToast._class_registered = True

    def show(self, text: str, kind: str = "info") -> None:
        self.close()
        self.text = text.strip()
        if not self.text:
            return
        self.kind = kind if kind in self.COLOR_BAR else "info"
        self.dpi = self._dpi()
        hinst = kernel32.GetModuleHandleW(None)
        self._register(hinst)
        self.font = gdi32.CreateFontW(
            -self._scale(15), 0, 0, 0, FW_NORMAL, 0, 0, 0,
            DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, "Microsoft YaHei UI",
        )
        pad_x = self._scale(16)
        pad_y = self._scale(12)
        bar = self._scale(6)
        max_w = self._scale(300)
        hdc = user32.GetDC(None)
        old = gdi32.SelectObject(hdc, self.font) if self.font else None
        text_rc = RECT(0, 0, max_w - bar - pad_x * 2, 0)
        user32.DrawTextW(
            hdc, self.text, -1, ctypes.byref(text_rc),
            DT_WORDBREAK | DT_CALCRECT | DT_NOPREFIX | DT_LEFT,
        )
        if old:
            gdi32.SelectObject(hdc, old)
        user32.ReleaseDC(None, hdc)
        text_w = max(text_rc.right, self._scale(80))
        text_h = max(text_rc.bottom, self._scale(20))
        width = min(max_w, bar + pad_x * 2 + text_w)
        height = pad_y * 2 + text_h

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        mon = user32.MonitorFromWindow(self.owner.hwnd, MONITOR_DEFAULTTONEAREST) if self.owner.hwnd else 0
        work = RECT(0, 0, 1920, 1080)
        if mon and user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            work = mi.rcWork
        pos_x = work.right - width - self._scale(16)
        pos_y = work.bottom - height - self._scale(16)
        if pos_x < work.left:
            pos_x = work.left + self._scale(8)
        if pos_y < work.top:
            pos_y = work.top + self._scale(8)

        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
            self.CLASS_NAME,
            TITLE,
            WS_POPUP,
            pos_x,
            pos_y,
            width,
            height,
            self.owner.hwnd,
            None,
            hinst,
            None,
        )
        if not self.hwnd:
            self._cleanup()
            return
        _TOASTS[int(self.hwnd)] = self
        TrayToast._current = self
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(self.hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x0013)  # NOSIZE|NOMOVE|NOACTIVATE
        user32.UpdateWindow(self.hwnd)
        timeout = 4000 if self.kind == "info" else 5500 if self.kind == "warn" else 7000
        user32.SetTimer(self.hwnd, 1, timeout, None)

    def close(self) -> None:
        current = TrayToast._current
        if current is not None and current is not self:
            current._destroy()
        self._destroy()

    def _destroy(self) -> None:
        hwnd = self.hwnd
        self.hwnd = None
        if TrayToast._current is self:
            TrayToast._current = None
        if hwnd and user32.IsWindow(hwnd):
            user32.KillTimer(hwnd, 1)
            user32.DestroyWindow(hwnd)
        self._cleanup()

    def _cleanup(self) -> None:
        if self.font:
            gdi32.DeleteObject(self.font)
            self.font = None

    def _paint(self, hwnd) -> None:
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        client = RECT()
        user32.GetClientRect(hwnd, ctypes.byref(client))
        br_bg = gdi32.CreateSolidBrush(self.COLOR_BG)
        user32.FillRect(hdc, ctypes.byref(client), br_bg)
        bar_w = self._scale(6)
        bar_rc = RECT(0, 0, bar_w, client.bottom)
        br_bar = gdi32.CreateSolidBrush(self.COLOR_BAR.get(self.kind, self.COLOR_BAR["info"]))
        user32.FillRect(hdc, ctypes.byref(bar_rc), br_bar)
        if self.font:
            old_font = gdi32.SelectObject(hdc, self.font)
        else:
            old_font = None
        gdi32.SetBkMode(hdc, TRANSPARENT)
        gdi32.SetTextColor(hdc, self.COLOR_TEXT)
        pad_x = self._scale(16)
        pad_y = self._scale(12)
        text_rc = RECT(bar_w + pad_x, pad_y, client.right - pad_x, client.bottom - pad_y)
        user32.DrawTextW(
            hdc, self.text, -1, ctypes.byref(text_rc),
            DT_LEFT | DT_WORDBREAK | DT_NOPREFIX,
        )
        pen = gdi32.CreatePen(PS_SOLID, self._scale(1), self.COLOR_BORDER)
        old_pen = gdi32.SelectObject(hdc, pen)
        null_brush = ctypes.windll.gdi32.GetStockObject(5)
        old_br = gdi32.SelectObject(hdc, null_brush)
        ctypes.windll.gdi32.Rectangle(hdc, client.left, client.top, client.right, client.bottom)
        gdi32.SelectObject(hdc, old_br)
        gdi32.SelectObject(hdc, old_pen)
        gdi32.DeleteObject(pen)
        gdi32.DeleteObject(br_bg)
        gdi32.DeleteObject(br_bar)
        if old_font:
            gdi32.SelectObject(hdc, old_font)
        user32.EndPaint(hwnd, ctypes.byref(ps))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        inst = _TOASTS.get(int(hwnd), self)
        if msg in (WM_PAINT, WM_PRINTCLIENT):
            inst._paint(hwnd)
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_TIMER:
            inst._destroy()
            return 0
        if msg in (WM_LBUTTONUP, WM_RBUTTONUP):
            inst._destroy()
            return 0
        if msg == WM_DESTROY:
            _TOASTS.pop(int(hwnd), None)
            if TrayToast._current is inst:
                TrayToast._current = None
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_TOASTS: dict[int, TrayToast] = {}


class TrayApp:
    def __init__(self) -> None:
        self.hwnd = None
        self.mutex = None
        self.nid = None
        self.state = "idle"
        self.stop_flag = False
        self.worker: threading.Thread | None = None
        self.pending: list[tuple[str, str, int]] = []
        self.lock = threading.Lock()
        self._toast = None
        self._menu_open = False
        self._open_menu = None
        self._ignore_tray_until = 0.0
        self._log_path = Path(__file__).resolve().parents[2] / "tray.log"
        self.icons = {
            "idle": _load_icon("tray-idle.ico"),
            "connect": _load_icon("tray-connect.ico"),
            "wait": _load_icon("tray-wait.ico"),
            "run": _load_icon("tray-run.ico"),
        }
        self.wndproc = WNDPROCTYPE(self._wndproc)

    def already_running(self) -> bool:
        self.mutex = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        return kernel32.GetLastError() == ERROR_ALREADY_EXISTS

    def run(self) -> int:
        if sys.platform != "win32":
            print("这个托盘程序只能在 Windows 上运行。")
            return 2
        if self.already_running():
            user32.MessageBoxW(None, "录音豆麦克风已经在运行，请看任务栏托盘。", TITLE, 0x40)
            return 0
        hinst = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSEXW()
        cls.cbSize = ctypes.sizeof(WNDCLASSEXW)
        cls.lpfnWndProc = self.wndproc
        cls.hInstance = hinst
        cls.hIcon = self.icons["idle"]
        cls.lpszClassName = "KunSoundcoreWorkMicTrayWindow"
        if not user32.RegisterClassExW(ctypes.byref(cls)):
            user32.MessageBoxW(None, "无法注册托盘窗口。", TITLE, 0x10)
            return 2
        # A real hidden top-level window is required so Win11 can theme
        # the context-menu text. A message-only window often yields a blank
        # white menu with only the separator visible.
        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOOLWINDOW,
            cls.lpszClassName,
            TITLE,
            WS_POPUP,
            0,
            0,
            0,
            0,
            None,
            None,
            hinst,
            None,
        )
        if not self.hwnd:
            user32.MessageBoxW(None, "无法创建托盘窗口。", TITLE, 0x10)
            return 2
        user32.ShowWindow(self.hwnd, SW_HIDE)
        self._add_icon()
        self._balloon("录音豆麦克风已在托盘里。点图标可以开始或停止。", "idle")
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return 0

    def _log(self, line: str) -> None:
        try:
            path = getattr(self, "_log_path", None) or (Path(__file__).resolve().parents[2] / "tray.log")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + line + "\n")
        except Exception:
            pass

    def _add_icon(self) -> None:
        self.nid = NOTIFYICONDATAW()
        self.nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        self.nid.hWnd = self.hwnd
        self.nid.uID = 1
        self.nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self.nid.uCallbackMessage = WM_TRAY
        self.nid.hIcon = self.icons["idle"]
        self.nid.szTip = "录音豆麦克风：未连接"
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid)):
            raise RuntimeError("无法创建托盘图标")
        self.nid.uVersion = NOTIFYICON_VERSION_4
        shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(self.nid))

    def _tip_for_state(self) -> str:
        return {
            "idle": "录音豆麦克风：未连接",
            "starting": "录音豆麦克风：正在连接…",
            "waiting": "录音豆麦克风：已连上，请按录音键",
            "running": "录音豆麦克风：已连上，正在听",
            "stopping": "录音豆麦克风：正在停止…",
        }.get(self.state, "录音豆麦克风")

    def _icon_for_state(self) -> int:
        if self.state == "starting":
            return self.icons["connect"]
        if self.state in {"waiting", "stopping"}:
            return self.icons["wait"]
        if self.state == "running":
            return self.icons["run"]
        return self.icons["idle"]

    def _apply_icon(self, balloon: str | None = None, kind: str = "info") -> None:
        if self.nid is None:
            return
        self.nid.hIcon = self._icon_for_state()
        self.nid.szTip = self._tip_for_state()[:127]
        flags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        if balloon:
            flags |= NIF_INFO
            self.nid.szInfo = balloon[:255]
            self.nid.szInfoTitle = TITLE
            self.nid.dwInfoFlags = {
                "info": NIIF_INFO | NIIF_NOSOUND,
                "warn": NIIF_WARNING | NIIF_NOSOUND,
                "error": NIIF_ERROR | NIIF_NOSOUND,
            }.get(kind, NIIF_INFO | NIIF_NOSOUND)
        else:
            self.nid.szInfo = ""
            self.nid.szInfoTitle = ""
            self.nid.dwInfoFlags = 0
        self.nid.uFlags = flags
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid))
        if balloon:
            self._show_toast(balloon, kind)

    def _toast_text(self, message: str) -> str:
        if not message or message.startswith("__"):
            return ""
        if "正在传输声音" in message:
            return "已连上，正在听"
        if "已连上" in message or "请按下录音豆" in message:
            return "已连上，请按一下录音豆开始录音"
        if "正在开始桥接" in message or "正在扫描" in message or "正在连接" in message or "正在打开" in message or "虚拟声卡已打开" in message:
            return "正在连接录音豆…"
        if "正在停止桥接" in message:
            return "正在停止桥接…"
        return message

    def _show_toast(self, message: str, kind: str = "info") -> None:
        text = self._toast_text(message)
        if not text:
            return
        if not hasattr(self, "_toast") or self._toast is None:
            self._toast = TrayToast(self)
        self._toast.show(text, kind)

    def _balloon(self, text: str, kind: str = "info") -> None:
        self._apply_icon(text, kind)

    def _set_state(self, state: str) -> None:
        self.state = state
        self._apply_icon()

    def _post_status(self, message: str, kind: str = "info") -> None:
        lowered = message
        with self.lock:
            self.pending.append((lowered, kind, 0))
        user32.PostMessageW(self.hwnd, WM_STATUS, 0, 0)

    def _on_status(self, message: str) -> None:
        kind = "info"
        if any(token in message for token in ("失败", "无法", "没有找到", "没有等到", "没有收到")):
            kind = "error"
        elif "请按" in message or "请再按" in message:
            kind = "warn" if "停" in message else "info"
        next_state = None
        if "正在传输声音" in message:
            next_state = "running"
        elif "正在扫描" in message or "正在连接" in message or "正在打开" in message or "虚拟声卡已打开" in message:
            next_state = "starting"
        elif "请按下录音豆" in message or "已连上" in message:
            next_state = "waiting"
        self._log(f"status state={self.state} next={next_state} kind={kind} {message}")
        with self.lock:
            self.pending.append((message, kind, 1 if next_state == "waiting" else 0))
            if next_state:
                # store desired state in a side channel via message kind prefix
                self.pending.append((f"__state__:{next_state}", "info", 0))
        user32.PostMessageW(self.hwnd, WM_STATUS, 0, 0)

    def _drain_status(self) -> None:
        with self.lock:
            items = list(self.pending)
            self.pending.clear()
        balloon = None
        kind = "info"
        for message, item_kind, _flag in items:
            if message.startswith("__state__:"):
                self.state = message.split(":", 1)[1]
                continue
            if message.startswith("__"):
                self._log(f"ignore sentinel {message}")
                continue
            balloon = message
            kind = item_kind
            if "正在传输声音" in message:
                self.state = "running"
            elif "已连上" in message or "请按下录音豆" in message:
                self.state = "waiting"
            elif "正在扫描" in message or "正在连接" in message or "正在打开" in message or "虚拟声卡已打开" in message:
                if self.state not in {"waiting", "running"}:
                    self.state = "starting"
        if balloon:
            self._apply_icon(balloon, kind)
        else:
            self._apply_icon()

    def _on_done(self, code: int) -> None:
        self._log(f"done code={code}")
        user32.PostMessageW(self.hwnd, WM_DONE, code & 0xFFFFFFFF, 0)

    def _start(self) -> None:
        if self.state not in {"idle"}:
            self._balloon("正在连接或已经在桥接。要停止请选「停止桥接」。")
            return
        self.stop_flag = False
        self._log("user start")
        self._set_state("starting")
        self._balloon("正在开始桥接，请稍等…")
        self.worker = threading.Thread(target=self._worker, name="soundcore-bridge", daemon=True)
        self.worker.start()

    def _request_stop(self) -> None:
        if self.state in {"idle"}:
            self._balloon("现在没有在桥接。")
            return
        self.stop_flag = True
        self._set_state("stopping")
        self._balloon("正在停止桥接…")

    def _worker(self) -> None:
        from soundcore_diag.live import run_cable_session

        def stop() -> bool:
            return self.stop_flag

        try:
            self._log("worker start")
            code = asyncio.run(run_cable_session(stop=stop, on_status=self._on_status))
            self._log(f"worker return {code}")
        except Exception:
            self._log("worker exception\n" + traceback.format_exc())
            self._post_status("桥接出错，已停止。", "error")
            code = 2
        self._on_done(code)

    def _finish(self, code: int) -> None:
        self._log(f"finish code={code} state={self.state}")
        self.stop_flag = False
        self.worker = None
        # Show any last real status first, then return the icon to idle.
        self._drain_status()
        self._set_state("idle")

    def _bring_to_foreground(self, hwnd=None) -> None:
        target = hwnd or self.hwnd
        fg = user32.GetForegroundWindow()
        attached = False
        fg_tid = 0
        if fg and fg != target:
            fg_tid = user32.GetWindowThreadProcessId(fg, None)
            our_tid = kernel32.GetCurrentThreadId()
            if fg_tid and fg_tid != our_tid:
                attached = bool(user32.AttachThreadInput(our_tid, fg_tid, True))
        user32.SetForegroundWindow(target)
        if attached and fg_tid:
            user32.AttachThreadInput(kernel32.GetCurrentThreadId(), fg_tid, False)

    def _popup(self) -> None:
        # Native TrackPopupMenu on this machine draws a blank white box
        # (separator only). Draw a custom menu with explicit dark text.
        now = time.monotonic()
        if now < getattr(self, "_ignore_tray_until", 0.0):
            return
        if getattr(self, "_menu_open", False):
            # A later click on the tray icon dismisses the open menu.
            # Ignore trailing events from the same click that opened it
            # (NIN_SELECT, button-up, and context-menu can arrive together).
            menu = getattr(self, "_open_menu", None)
            if menu is not None and getattr(menu, "_can_dismiss", False):
                self._log("popup toggle-close")
                menu._close(0)
                self._ignore_tray_until = time.monotonic() + TRAY_CLICK_GUARD_SEC
            return
        self._menu_open = True
        # Hold off additional tray events from this same click.
        self._ignore_tray_until = now + TRAY_CLICK_GUARD_SEC
        try:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            menu = TrayMenu(self)
            self._open_menu = menu
            self._log("popup open")
            cmd = menu.show(pt.x, pt.y)
            self._log(f"popup close cmd={cmd}")
            if cmd == ID_START:
                self._start()
            elif cmd == ID_STOP:
                self._request_stop()
            elif cmd == ID_EXIT:
                self._exit()
        finally:
            self._open_menu = None
            self._menu_open = False

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event in (
                WM_RBUTTONUP,
                WM_LBUTTONUP,
                WM_LBUTTONDBLCLK,
                WM_CONTEXTMENU,
                NIN_SELECT,
                NIN_KEYSELECT,
            ):
                self._popup()
                return 0
        elif msg == WM_COMMAND:
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
        elif msg == WM_DESTROY:
            if self.nid is not None:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _exit(self) -> None:
        if self.state != "idle":
            self.stop_flag = True
            self._set_state("stopping")
            worker = self.worker
            if worker is not None:
                worker.join(8)
        if getattr(self, "_toast", None) is not None:
            self._toast.close()
            self._toast = None
        if self.nid is not None:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
            self.nid = None
        user32.DestroyWindow(self.hwnd)


def main(argv: list[str] | None = None) -> int:
    del argv
    return TrayApp().run()


if __name__ == "__main__":
    raise SystemExit(main())
