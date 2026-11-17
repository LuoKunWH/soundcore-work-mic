"""Win32 declarations used by the tray. Importable on Windows only."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
gdi32 = ctypes.windll.gdi32

LRESULT = ctypes.c_ssize_t
WNDPROCTYPE = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_ACTIVATE = 0x0006
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_MOUSEACTIVATE = 0x0021
WM_CONTEXTMENU = 0x007B
WM_KEYDOWN = 0x0100
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_MOUSELEAVE = 0x02A3
WM_PRINTCLIENT = 0x0318
WM_APP = 0x8000
NIN_SELECT = 0x0400
NIN_KEYSELECT = 0x0401

VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_UP = 0x26
VK_DOWN = 0x28
WA_INACTIVE = 0
MA_ACTIVATE = 1

CS_VREDRAW = 0x0001
CS_HREDRAW = 0x0002
CS_DROPSHADOW = 0x00020000
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = wintypes.HWND(-1)
LWA_ALPHA = 0x00000002
SM_CXSMICON = 49

DT_LEFT = 0x0000
DT_CENTER = 0x0001
DT_RIGHT = 0x0002
DT_VCENTER = 0x0004
DT_WORDBREAK = 0x0010
DT_SINGLELINE = 0x0020
DT_CALCRECT = 0x0400
DT_NOPREFIX = 0x0800
DT_END_ELLIPSIS = 0x8000
TRANSPARENT = 1
FW_NORMAL = 400
FW_BOLD = 700
DEFAULT_CHARSET = 1
CLEARTYPE_QUALITY = 5
PS_SOLID = 0
NULL_BRUSH = 5
NULL_PEN = 8
SRCCOPY = 0x00CC0020
IDC_ARROW = 32512
IDC_HAND = 32649
IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
MONITOR_DEFAULTTONEAREST = 2
TME_LEAVE = 0x00000002
ERROR_ALREADY_EXISTS = 183

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETVERSION = 4
NOTIFYICON_VERSION_4 = 4
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_SHOWTIP = 0x00000080

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUND = 2


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


class NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("guidItem", GUID),
    ]


class GdiplusStartupInput(ctypes.Structure):
    _fields_ = [
        ("GdiplusVersion", ctypes.c_uint32),
        ("DebugEventCallback", ctypes.c_void_p),
        ("SuppressBackgroundThread", wintypes.BOOL),
        ("SuppressExternalCodecs", wintypes.BOOL),
    ]


def _sig(func, restype, *argtypes) -> None:
    func.argtypes = list(argtypes)
    func.restype = restype


_P = ctypes.c_void_p
_INT = ctypes.c_int
_H = wintypes.HWND

_sig(kernel32.GetModuleHandleW, wintypes.HMODULE, wintypes.LPCWSTR)
_sig(kernel32.CreateMutexW, wintypes.HANDLE, _P, wintypes.BOOL, wintypes.LPCWSTR)
_sig(kernel32.GetLastError, wintypes.DWORD)
_sig(kernel32.GetCurrentThreadId, wintypes.DWORD)

_sig(user32.RegisterClassExW, wintypes.ATOM, ctypes.POINTER(WNDCLASSEXW))
_sig(
    user32.CreateWindowExW,
    _H,
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    _INT, _INT, _INT, _INT,
    _H, wintypes.HMENU, wintypes.HINSTANCE, _P,
)
_sig(user32.DefWindowProcW, LRESULT, _H, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_sig(user32.DestroyWindow, wintypes.BOOL, _H)
_sig(user32.IsWindow, wintypes.BOOL, _H)
_sig(user32.ShowWindow, wintypes.BOOL, _H, _INT)
_sig(user32.UpdateWindow, wintypes.BOOL, _H)
_sig(user32.SetWindowPos, wintypes.BOOL, _H, _H, _INT, _INT, _INT, _INT, wintypes.UINT)
_sig(user32.GetMessageW, _INT, ctypes.POINTER(MSG), _H, wintypes.UINT, wintypes.UINT)
_sig(user32.TranslateMessage, wintypes.BOOL, ctypes.POINTER(MSG))
_sig(user32.DispatchMessageW, LRESULT, ctypes.POINTER(MSG))
_sig(user32.PostMessageW, wintypes.BOOL, _H, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_sig(user32.PostQuitMessage, None, _INT)
_sig(user32.MessageBoxW, _INT, _H, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT)
_sig(user32.LoadImageW, wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, _INT, _INT, wintypes.UINT)
_sig(user32.LoadIconW, wintypes.HICON, wintypes.HINSTANCE, _P)
_sig(user32.LoadCursorW, wintypes.HANDLE, wintypes.HINSTANCE, _P)
_sig(user32.GetSystemMetrics, _INT, _INT)
_sig(user32.GetCursorPos, wintypes.BOOL, ctypes.POINTER(POINT))
_sig(user32.MonitorFromPoint, wintypes.HMONITOR, POINT, wintypes.DWORD)
_sig(user32.GetMonitorInfoW, wintypes.BOOL, wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))
_sig(user32.TrackMouseEvent, wintypes.BOOL, ctypes.POINTER(TRACKMOUSEEVENT))
_sig(user32.InvalidateRect, wintypes.BOOL, _H, _P, wintypes.BOOL)
_sig(user32.BeginPaint, wintypes.HDC, _H, ctypes.POINTER(PAINTSTRUCT))
_sig(user32.EndPaint, wintypes.BOOL, _H, ctypes.POINTER(PAINTSTRUCT))
_sig(user32.GetClientRect, wintypes.BOOL, _H, ctypes.POINTER(RECT))
_sig(user32.FillRect, _INT, wintypes.HDC, ctypes.POINTER(RECT), wintypes.HBRUSH)
_sig(user32.DrawTextW, _INT, wintypes.HDC, wintypes.LPCWSTR, _INT, ctypes.POINTER(RECT), wintypes.UINT)
_sig(user32.GetDC, wintypes.HDC, _H)
_sig(user32.ReleaseDC, _INT, _H, wintypes.HDC)
_sig(user32.SetTimer, ctypes.c_size_t, _H, ctypes.c_size_t, wintypes.UINT, _P)
_sig(user32.KillTimer, wintypes.BOOL, _H, ctypes.c_size_t)
_sig(user32.SetForegroundWindow, wintypes.BOOL, _H)
_sig(user32.GetForegroundWindow, _H)
_sig(user32.GetWindowThreadProcessId, wintypes.DWORD, _H, ctypes.POINTER(wintypes.DWORD))
_sig(user32.AttachThreadInput, wintypes.BOOL, wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
_sig(user32.SetLayeredWindowAttributes, wintypes.BOOL, _H, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD)

_sig(shell32.Shell_NotifyIconW, wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW))
_sig(shell32.Shell_NotifyIconGetRect, ctypes.c_long, ctypes.POINTER(NOTIFYICONIDENTIFIER), ctypes.POINTER(RECT))
_sig(shell32.ShellExecuteW, wintypes.HINSTANCE, _H, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, _INT)

_sig(
    gdi32.CreateFontW,
    wintypes.HANDLE,
    _INT, _INT, _INT, _INT, _INT,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
)
_sig(gdi32.CreateSolidBrush, wintypes.HBRUSH, wintypes.COLORREF)
_sig(gdi32.CreatePen, wintypes.HANDLE, _INT, _INT, wintypes.COLORREF)
_sig(gdi32.GetStockObject, wintypes.HANDLE, _INT)
_sig(gdi32.SelectObject, wintypes.HANDLE, wintypes.HDC, wintypes.HANDLE)
_sig(gdi32.DeleteObject, wintypes.BOOL, wintypes.HANDLE)
_sig(gdi32.SetTextColor, wintypes.COLORREF, wintypes.HDC, wintypes.COLORREF)
_sig(gdi32.SetBkMode, _INT, wintypes.HDC, _INT)
_sig(gdi32.CreateCompatibleDC, wintypes.HDC, wintypes.HDC)
_sig(gdi32.CreateCompatibleBitmap, wintypes.HANDLE, wintypes.HDC, _INT, _INT)
_sig(gdi32.DeleteDC, wintypes.BOOL, wintypes.HDC)
_sig(gdi32.BitBlt, wintypes.BOOL, wintypes.HDC, _INT, _INT, _INT, _INT, wintypes.HDC, _INT, _INT, wintypes.DWORD)
_sig(gdi32.RoundRect, wintypes.BOOL, wintypes.HDC, _INT, _INT, _INT, _INT, _INT, _INT)
_sig(gdi32.Ellipse, wintypes.BOOL, wintypes.HDC, _INT, _INT, _INT, _INT)
_sig(gdi32.Rectangle, wintypes.BOOL, wintypes.HDC, _INT, _INT, _INT, _INT)


def _load_gdiplus():
    """GDI+ gives anti-aliased shapes. Without it the tray falls back to GDI."""
    try:
        lib = ctypes.windll.gdiplus
        real = ctypes.c_float
        out = ctypes.POINTER(_P)
        _sig(lib.GdiplusStartup, _INT, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(GdiplusStartupInput), _P)
        _sig(lib.GdipCreateFromHDC, _INT, wintypes.HDC, out)
        _sig(lib.GdipDeleteGraphics, _INT, _P)
        _sig(lib.GdipSetSmoothingMode, _INT, _P, _INT)
        _sig(lib.GdipSetPixelOffsetMode, _INT, _P, _INT)
        _sig(lib.GdipCreateSolidFill, _INT, ctypes.c_uint32, out)
        _sig(lib.GdipDeleteBrush, _INT, _P)
        _sig(lib.GdipCreatePen1, _INT, ctypes.c_uint32, real, _INT, out)
        _sig(lib.GdipDeletePen, _INT, _P)
        _sig(lib.GdipCreatePath, _INT, _INT, out)
        _sig(lib.GdipDeletePath, _INT, _P)
        _sig(lib.GdipAddPathArc, _INT, _P, real, real, real, real, real, real)
        _sig(lib.GdipClosePathFigure, _INT, _P)
        _sig(lib.GdipFillPath, _INT, _P, _P, _P)
        _sig(lib.GdipDrawPath, _INT, _P, _P, _P)
        _sig(lib.GdipFillEllipse, _INT, _P, _P, real, real, real, real)
        token = ctypes.c_size_t()
        startup = GdiplusStartupInput(1, None, False, False)
        if lib.GdiplusStartup(ctypes.byref(token), ctypes.byref(startup), None) != 0:
            return None
        return lib
    except (OSError, AttributeError):
        return None


gdiplus = _load_gdiplus()


def enable_dpi_awareness() -> None:
    """Ask for per-monitor DPI so the panel is drawn sharp on scaled displays."""
    try:
        setter = user32.SetProcessDpiAwarenessContext
        setter.argtypes = [_P]
        setter.restype = wintypes.BOOL
        if setter(_P(-4)):  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def monitor_at(x: int, y: int):
    """Return (work area RECT, dpi) of the monitor nearest to a point."""
    work = RECT(0, 0, 1920, 1080)
    dpi = 96
    mon = user32.MonitorFromPoint(POINT(x, y), MONITOR_DEFAULTTONEAREST)
    if mon:
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            work = info.rcWork
        try:
            dx = wintypes.UINT()
            dy = wintypes.UINT()
            getter = ctypes.windll.shcore.GetDpiForMonitor
            getter.argtypes = [wintypes.HMONITOR, _INT, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
            getter.restype = ctypes.c_long
            if getter(mon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0 and dx.value:
                dpi = int(dx.value)
        except (AttributeError, OSError):
            pass
    return work, dpi


def dwm_set(hwnd, attribute: int, value: int) -> bool:
    try:
        func = ctypes.windll.dwmapi.DwmSetWindowAttribute
        func.argtypes = [_H, wintypes.DWORD, _P, wintypes.DWORD]
        func.restype = ctypes.c_long
        data = ctypes.c_int(value)
        return func(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data)) == 0
    except (AttributeError, OSError):
        return False


def system_uses_dark() -> bool:
    """True when the taskbar and its flyouts are dark."""
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            for name in ("SystemUsesLightTheme", "AppsUseLightTheme"):
                try:
                    value, _kind = winreg.QueryValueEx(key, name)
                    return int(value) == 0
                except OSError:
                    continue
    except OSError:
        pass
    return False


def colorref(rgb: int) -> int:
    """0xRRGGBB to COLORREF (0x00BBGGRR)."""
    return ((rgb & 0xFF) << 16) | (rgb & 0xFF00) | ((rgb >> 16) & 0xFF)
