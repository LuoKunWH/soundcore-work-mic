"""The tray panel and the notification card. Importable on Windows only.

Both are small owner-drawn popup windows. Shapes are drawn with GDI+ so the
edges are smooth, text with GDI so it keeps ClearType. The views know nothing
about the bridge: they draw a state name, an optional notice and a timer.
"""

from __future__ import annotations

import ctypes
import time
import traceback
from dataclasses import dataclass

from soundcore_diag import tray_win32 as w
from soundcore_diag import version
from soundcore_diag.tray_model import (
    BEAN_BODY,
    BEAN_CLIP,
    CLIP_SHADE,
    GLYPHS,
    STEPS,
    TITLE,
    TONES,
    Notice,
    delete_prompt,
    shade,
    state_view,
    total_label,
)

FONT_FACE = "Microsoft YaHei UI"
VERSION_LABEL = version.label(with_branch=False)
WM_ENABLE_DISMISS = w.WM_APP + 10
WM_CLICKED_OUTSIDE = w.WM_APP + 11
# After an outside click closes the panel, the same click may reach the tray
# icon; ignore tray events this long so it does not reopen at once.
DISMISS_GUARD_SEC = 0.4
TIMER_TICK = 1
TIMER_LIFE = 1
TIMER_FADE_IN = 2
TIMER_FADE_OUT = 3


@dataclass(frozen=True)
class Theme:
    bg: int
    text: int
    text2: int
    text3: int
    divider: int
    border: int
    hover: int
    pressed: int
    track: int
    button: int
    button_hover: int
    button_pressed: int
    button_border: int
    accent: int
    accent_hover: int
    accent_pressed: int
    on_accent: int
    segment: int


LIGHT = Theme(
    bg=0xF9F9F9, text=0x1A1A1A, text2=0x5C5C5C, text3=0x9A9A9A,
    divider=0xE6E6E6, border=0xD4D4D4, hover=0xEDEDED, pressed=0xE4E4E4, track=0xE2E2E2,
    button=0xFFFFFF, button_hover=0xF4F4F4, button_pressed=0xEBEBEB, button_border=0xD9D9D9,
    accent=0x2F6BFF, accent_hover=0x2860E8, accent_pressed=0x2255CF, on_accent=0xFFFFFF, segment=0xFFFFFF,
)
DARK = Theme(
    bg=0x2B2B2B, text=0xFFFFFF, text2=0xC6C6C6, text3=0x858585,
    divider=0x3B3B3B, border=0x484848, hover=0x383838, pressed=0x333333, track=0x434343,
    button=0x383838, button_hover=0x414141, button_pressed=0x353535, button_border=0x4A4A4A,
    accent=0x6C9BFF, accent_hover=0x7CA6FF, accent_pressed=0x5F8CEB, on_accent=0x0B1530, segment=0x5A5A5A,
)


class Fonts:
    def __init__(self, dpi: int) -> None:
        self.dpi = dpi
        self._cache: dict[tuple[int, bool], int] = {}

    def get(self, px: float, bold: bool = False):
        height = max(1, int(round(px * self.dpi / 96.0)))
        key = (height, bold)
        if key not in self._cache:
            self._cache[key] = w.gdi32.CreateFontW(
                -height, 0, 0, 0, w.FW_BOLD if bold else w.FW_NORMAL, 0, 0, 0,
                w.DEFAULT_CHARSET, 0, 0, w.CLEARTYPE_QUALITY, 0, FONT_FACE,
            )
        return self._cache[key]

    def close(self) -> None:
        for handle in self._cache.values():
            if handle:
                w.gdi32.DeleteObject(handle)
        self._cache.clear()


class Canvas:
    """Filled shapes on a device context: GDI+ when available, GDI otherwise."""

    def __init__(self, hdc) -> None:
        self.hdc = hdc
        self.g = None
        if w.gdiplus is not None:
            graphics = ctypes.c_void_p()
            if w.gdiplus.GdipCreateFromHDC(hdc, ctypes.byref(graphics)) == 0 and graphics.value:
                self.g = graphics
                w.gdiplus.GdipSetSmoothingMode(graphics, 4)  # anti-alias
                w.gdiplus.GdipSetPixelOffsetMode(graphics, 4)  # half pixel

    def finish(self) -> None:
        if self.g is not None:
            w.gdiplus.GdipDeleteGraphics(self.g)
            self.g = None

    def _path(self, x: float, y: float, width: float, height: float, radius: float):
        path = ctypes.c_void_p()
        w.gdiplus.GdipCreatePath(0, ctypes.byref(path))
        d = max(0.01, min(radius * 2.0, width, height))
        w.gdiplus.GdipAddPathArc(path, x, y, d, d, 180.0, 90.0)
        w.gdiplus.GdipAddPathArc(path, x + width - d, y, d, d, 270.0, 90.0)
        w.gdiplus.GdipAddPathArc(path, x + width - d, y + height - d, d, d, 0.0, 90.0)
        w.gdiplus.GdipAddPathArc(path, x, y + height - d, d, d, 90.0, 90.0)
        w.gdiplus.GdipClosePathFigure(path)
        return path

    def round_rect(self, x, y, width, height, radius, fill=None, stroke=None, stroke_width=1.0) -> None:
        if width <= 0 or height <= 0:
            return
        if self.g is not None:
            if fill is not None:
                path = self._path(x, y, width, height, radius)
                brush = ctypes.c_void_p()
                w.gdiplus.GdipCreateSolidFill(0xFF000000 | fill, ctypes.byref(brush))
                w.gdiplus.GdipFillPath(self.g, brush, path)
                w.gdiplus.GdipDeleteBrush(brush)
                w.gdiplus.GdipDeletePath(path)
            if stroke is not None:
                half = stroke_width / 2.0
                path = self._path(x + half, y + half, width - stroke_width, height - stroke_width, radius - half)
                pen = ctypes.c_void_p()
                w.gdiplus.GdipCreatePen1(0xFF000000 | stroke, stroke_width, 2, ctypes.byref(pen))
                w.gdiplus.GdipDrawPath(self.g, pen, path)
                w.gdiplus.GdipDeletePen(pen)
                w.gdiplus.GdipDeletePath(path)
            return
        brush = w.gdi32.CreateSolidBrush(w.colorref(fill)) if fill is not None else w.gdi32.GetStockObject(w.NULL_BRUSH)
        if stroke is not None:
            pen = w.gdi32.CreatePen(w.PS_SOLID, max(1, int(round(stroke_width))), w.colorref(stroke))
        else:
            pen = w.gdi32.GetStockObject(w.NULL_PEN)
        old_brush = w.gdi32.SelectObject(self.hdc, brush)
        old_pen = w.gdi32.SelectObject(self.hdc, pen)
        d = int(round(min(radius * 2.0, width, height)))
        extra = 0 if stroke is not None else 1
        w.gdi32.RoundRect(
            self.hdc, int(round(x)), int(round(y)),
            int(round(x + width)) + extra, int(round(y + height)) + extra, d, d,
        )
        w.gdi32.SelectObject(self.hdc, old_brush)
        w.gdi32.SelectObject(self.hdc, old_pen)
        if fill is not None:
            w.gdi32.DeleteObject(brush)
        if stroke is not None:
            w.gdi32.DeleteObject(pen)

    def disc(self, cx: float, cy: float, radius: float, fill: int) -> None:
        if self.g is not None:
            brush = ctypes.c_void_p()
            w.gdiplus.GdipCreateSolidFill(0xFF000000 | fill, ctypes.byref(brush))
            w.gdiplus.GdipFillEllipse(self.g, brush, cx - radius, cy - radius, radius * 2.0, radius * 2.0)
            w.gdiplus.GdipDeleteBrush(brush)
            return
        self.round_rect(cx - radius, cy - radius, radius * 2.0, radius * 2.0, radius, fill=fill)

    def badge(self, x: float, y: float, size: float, tone: str) -> None:
        """The tone-coloured bean with its white glyph, as on the tray icon."""
        rgb = TONES.get(tone, TONES["idle"])
        clip_cx, clip_top, clip_w, clip_h, clip_r = BEAN_CLIP
        self.round_rect(
            x + (clip_cx - clip_w / 2.0) * size, y + clip_top * size, clip_w * size, clip_h * size,
            clip_r * size, fill=shade(rgb, CLIP_SHADE),
        )
        body_cx, body_cy, body_r = BEAN_BODY
        self.disc(x + body_cx * size, y + body_cy * size, body_r * size, rgb)
        x = x + (body_cx - body_r) * size
        y = y + (body_cy - body_r) * size
        size = body_r * 2.0 * size
        for shape in GLYPHS.get(tone, ()):
            if shape[0] == "bar":
                _kind, cx, cy, width, height = shape
                self.round_rect(
                    x + (cx - width / 2.0) * size, y + (cy - height / 2.0) * size,
                    width * size, height * size, min(width, height) * size / 2.0, fill=0xFFFFFF,
                )
            else:
                _kind, cx, cy, radius = shape
                self.disc(x + cx * size, y + cy * size, radius * size, 0xFFFFFF)


def fill_background(hdc, width: int, height: int, rgb: int) -> None:
    brush = w.gdi32.CreateSolidBrush(w.colorref(rgb))
    rect = w.RECT(0, 0, width, height)
    w.user32.FillRect(hdc, ctypes.byref(rect), brush)
    w.gdi32.DeleteObject(brush)


def draw_frame(hdc, width: int, height: int, rgb: int) -> None:
    pen = w.gdi32.CreatePen(w.PS_SOLID, 1, w.colorref(rgb))
    old_pen = w.gdi32.SelectObject(hdc, pen)
    old_brush = w.gdi32.SelectObject(hdc, w.gdi32.GetStockObject(w.NULL_BRUSH))
    w.gdi32.Rectangle(hdc, 0, 0, width, height)
    w.gdi32.SelectObject(hdc, old_brush)
    w.gdi32.SelectObject(hdc, old_pen)
    w.gdi32.DeleteObject(pen)


def draw_text(hdc, font, text: str, box, rgb: int, flags: int) -> None:
    old = w.gdi32.SelectObject(hdc, font)
    w.gdi32.SetBkMode(hdc, w.TRANSPARENT)
    w.gdi32.SetTextColor(hdc, w.colorref(rgb))
    rect = w.RECT(*[int(round(v)) for v in box])
    w.user32.DrawTextW(hdc, text, -1, ctypes.byref(rect), flags | w.DT_NOPREFIX)
    w.gdi32.SelectObject(hdc, old)


def measure_text(hdc, font, text: str, width: int, wrap: bool = True) -> tuple[int, int]:
    old = w.gdi32.SelectObject(hdc, font)
    rect = w.RECT(0, 0, int(width), 0)
    flags = w.DT_CALCRECT | w.DT_NOPREFIX | (w.DT_WORDBREAK if wrap else w.DT_SINGLELINE)
    w.user32.DrawTextW(hdc, text, -1, ctypes.byref(rect), flags)
    w.gdi32.SelectObject(hdc, old)
    return rect.right, rect.bottom


def paint_buffered(hwnd, draw) -> None:
    """Run draw(hdc, width, height) on an off-screen bitmap, then show it."""
    ps = w.PAINTSTRUCT()
    hdc = w.user32.BeginPaint(hwnd, ctypes.byref(ps))
    client = w.RECT()
    w.user32.GetClientRect(hwnd, ctypes.byref(client))
    width, height = client.right, client.bottom
    mem = w.gdi32.CreateCompatibleDC(hdc)
    bitmap = w.gdi32.CreateCompatibleBitmap(hdc, max(1, width), max(1, height))
    old = w.gdi32.SelectObject(mem, bitmap)
    try:
        draw(mem, width, height)
        w.gdi32.BitBlt(hdc, 0, 0, width, height, mem, 0, 0, w.SRCCOPY)
    finally:
        w.gdi32.SelectObject(mem, old)
        w.gdi32.DeleteObject(bitmap)
        w.gdi32.DeleteDC(mem)
        w.user32.EndPaint(hwnd, ctypes.byref(ps))


def style_window(hwnd, theme: Theme, dark: bool) -> bool:
    """Round the corners on Windows 11. Returns False where that is not available."""
    w.dwm_set(hwnd, w.DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
    rounded = w.dwm_set(hwnd, w.DWMWA_WINDOW_CORNER_PREFERENCE, w.DWMWCP_ROUND)
    if rounded:
        w.dwm_set(hwnd, w.DWMWA_BORDER_COLOR, w.colorref(theme.border))
    return rounded


def register_class(name: str, proc, shadow: bool = True, icon=None) -> None:
    cls = w.WNDCLASSEXW()
    cls.cbSize = ctypes.sizeof(w.WNDCLASSEXW)
    cls.style = w.CS_HREDRAW | w.CS_VREDRAW | (w.CS_DROPSHADOW if shadow else 0)
    cls.lpfnWndProc = proc
    if icon:
        cls.hIcon = icon
        cls.hIconSm = icon
    cls.hInstance = w.kernel32.GetModuleHandleW(None)
    cls.hCursor = w.user32.LoadCursorW(None, ctypes.c_void_p(w.IDC_ARROW))
    cls.lpszClassName = name
    # Registering twice in one process fails harmlessly; the class stays usable.
    w.user32.RegisterClassExW(ctypes.byref(cls))


@dataclass(frozen=True)
class PanelModel:
    state: str = "idle"
    notice: Notice | None = None
    elapsed: str = ""
    mic: str = ""
    # (bean available, system microphone available); None hides the switch.
    mic_options: tuple[bool, bool] | None = None
    # Delete the recordings made as a microphone; None hides the row.
    auto_clean: bool | None = None


class PanelView:
    """Layout and drawing of the tray panel, in pixels of one DPI."""

    WIDTH = 264
    PAD = 12
    BADGE = 32
    BUTTON = 30
    ROW = 28
    SWITCH = 168
    FOOTER = (("recordings", "整理录音"), ("settings", "声音设置"), ("exit", "退出"))
    MIC = (("mic_bean", "录音豆"), ("mic_system", "系统麦克风"))
    CLEAN = (("clean_on", "开"), ("clean_off", "关"))

    def __init__(self, dpi: int, dark: bool) -> None:
        self.dpi = dpi
        self.theme = DARK if dark else LIGHT
        self.fonts = Fonts(dpi)
        self.width = self.s(self.WIDTH)
        self.height = 0
        self.items: list[tuple[str, tuple[int, int, int, int], bool]] = []
        self._hint_box = (0, 0, 0, 0)
        self._step_y = 0
        self._divider_y = 0
        self._mic_row: tuple[int, int, int, int] | None = None
        self._clean_row: tuple[int, int, int, int] | None = None

    def s(self, px: float) -> int:
        return int(round(px * self.dpi / 96.0))

    def close(self) -> None:
        self.fonts.close()

    @staticmethod
    def content(model: PanelModel):
        """(tone, headline, hint, view) for a model."""
        view = state_view(model.state)
        notice = model.notice
        if model.state == "idle" and notice is not None and notice.sticky:
            return notice.tone, notice.title, notice.body or view.hint, view
        return view.tone, view.headline, view.hint, view

    def layout(self, hdc, model: PanelModel) -> int:
        s = self.s
        pad = s(self.PAD)
        _tone, _headline, hint, view = self.content(model)
        inner = self.width - pad * 2
        y = pad + s(self.BADGE) + s(12)
        self._step_y = y
        y += s(3) + s(4) + s(14) + s(8)
        _w, hint_h = measure_text(hdc, self.fonts.get(12), hint, inner)
        hint_h = max(hint_h, s(16))
        self._hint_box = (pad, y, pad + inner, y + hint_h)
        y += hint_h + s(10)
        items = [("primary", (pad, y, pad + inner, y + s(self.BUTTON)), view.button_enabled)]
        y += s(self.BUTTON) + s(8)
        self._mic_row = None
        if model.mic_options is not None:
            row = s(self.ROW)
            left = pad + inner - s(self.SWITCH)
            self._mic_row = (pad, y, left, y + row)
            half = s(self.SWITCH) // 2
            for index, (name, _label) in enumerate(self.MIC):
                box = (left + half * index, y, pad + inner if index else left + half, y + row)
                items.append((name, box, model.mic_options[index]))
            y += row + s(8)
        self._clean_row = None
        if model.auto_clean is not None:
            row = s(self.ROW)
            left = pad + inner - s(self.SWITCH)
            self._clean_row = (pad, y, left, y + row)
            half = s(self.SWITCH) // 2
            for index, (name, _label) in enumerate(self.CLEAN):
                box = (left + half * index, y, pad + inner if index else left + half, y + row)
                items.append((name, box, True))
            y += row + s(8)
        self._divider_y = y
        y += max(1, s(1)) + s(4)
        count = len(self.FOOTER)
        cell = (self.width - s(4) * 2) // count
        for index, (name, _label) in enumerate(self.FOOTER):
            left = s(4) + cell * index
            items.append((name, (left, y, left + cell, y + s(self.ROW)), True))
        y += s(self.ROW) + s(4)
        self.items = items
        self.height = y
        return y

    def item_at(self, x: int, y: int) -> int:
        for index, (_name, (left, top, right, bottom), _enabled) in enumerate(self.items):
            if left <= x < right and top <= y < bottom:
                return index
        return -1

    def paint(
        self, hdc, model: PanelModel, hover: int = -1, pressed: int = -1, rounded: bool = True, surface: int = 0
    ) -> None:
        self.layout(hdc, model)
        s = self.s
        t = self.theme
        pad = s(self.PAD)
        badge = s(self.BADGE)
        inner = self.width - pad * 2
        tone, headline, hint, view = self.content(model)
        tone_rgb = TONES.get(tone, TONES["idle"])

        fill_background(hdc, self.width, max(self.height, surface), t.bg)
        canvas = Canvas(hdc)
        canvas.badge(pad, pad, badge, tone)

        gap = s(4)
        seg_w = (inner - gap * 2) / 3.0
        for index in range(3):
            canvas.round_rect(
                pad + index * (seg_w + gap), self._step_y, seg_w, s(3), s(1.5),
                fill=tone_rgb if index < view.step else t.track,
            )

        _name, (left, top, right, bottom), enabled = self.items[0]
        active = enabled and hover == 0
        down = active and pressed == 0
        if not enabled:
            canvas.round_rect(left, top, right - left, bottom - top, s(5), fill=t.track)
        elif view.button_primary:
            fill = t.accent_pressed if down else t.accent_hover if active else t.accent
            canvas.round_rect(left, top, right - left, bottom - top, s(5), fill=fill)
        else:
            fill = t.button_pressed if down else t.button_hover if active else t.button
            canvas.round_rect(
                left, top, right - left, bottom - top, s(5),
                fill=fill, stroke=t.button_border, stroke_width=max(1, s(1)),
            )

        for row in (self._mic_row, self._clean_row):
            if row is None:
                continue
            _l, top, track_left, bottom = row
            canvas.round_rect(track_left, top, pad + inner - track_left, bottom - top, s(6), fill=t.track)
        inset = s(2)
        for index, (name, (left, top, right, bottom), enabled) in enumerate(self.items):
            if not _is_segment(name):
                continue
            box = (left + inset, top + inset, right - left - inset * 2, bottom - top - inset * 2)
            if _segment_on(name, model):
                canvas.round_rect(
                    *box, s(5), fill=t.segment, stroke=t.button_border, stroke_width=max(1, s(1))
                )
            elif enabled and hover == index:
                canvas.round_rect(*box, s(5), fill=t.pressed if pressed == index else t.hover)

        canvas.round_rect(pad, self._divider_y, inner, max(1, s(1)), 0, fill=t.divider)
        footer = {name for name, _label in self.FOOTER}
        for index, (name, (left, top, right, bottom), _e) in enumerate(self.items):
            if name in footer and hover == index:
                canvas.round_rect(
                    left, top, right - left, bottom - top, s(5),
                    fill=t.pressed if pressed == index else t.hover,
                )
        canvas.finish()
        if not rounded:
            draw_frame(hdc, self.width, self.height, t.border)

        line = w.DT_SINGLELINE | w.DT_VCENTER | w.DT_END_ELLIPSIS
        text_x = pad + badge + s(10)
        right_edge = self.width - pad
        title_h = s(13)
        title_box = (text_x, pad, right_edge, pad + title_h)
        draw_text(hdc, self.fonts.get(10), VERSION_LABEL, title_box, t.text3, line | w.DT_RIGHT)
        draw_text(hdc, self.fonts.get(11), TITLE, title_box, t.text2, line)
        head_top, head_bottom = pad + title_h, pad + badge + s(2)
        elapsed_w = 0
        if model.elapsed:
            font = self.fonts.get(12)
            elapsed_w, _h = measure_text(hdc, font, model.elapsed, inner, wrap=False)
            draw_text(
                hdc, font, model.elapsed,
                (right_edge - elapsed_w, head_top, right_edge, head_bottom), t.text2, line | w.DT_RIGHT,
            )
            elapsed_w += s(8)
        draw_text(
            hdc, self.fonts.get(15, bold=True), headline,
            (text_x, head_top, right_edge - elapsed_w, head_bottom), t.text, line,
        )
        label_y = self._step_y + s(3) + s(4)
        for index, label in enumerate(STEPS):
            x = pad + index * (seg_w + gap)
            draw_text(
                hdc, self.fonts.get(11), label, (x, label_y, x + seg_w, label_y + s(14)),
                t.text if index < view.step else t.text3, line,
            )
        draw_text(hdc, self.fonts.get(12), hint, self._hint_box, t.text2, w.DT_WORDBREAK)

        _name, box, enabled = self.items[0]
        if not enabled:
            color = t.text3
        elif view.button_primary:
            color = t.on_accent
        else:
            color = t.text
        draw_text(hdc, self.fonts.get(13), view.button, box, color, line | w.DT_CENTER)
        labels = dict(self.FOOTER + self.MIC + self.CLEAN)
        if self._mic_row is not None:
            draw_text(hdc, self.fonts.get(12), "麦克风", self._mic_row, t.text2, line)
        if self._clean_row is not None:
            draw_text(hdc, self.fonts.get(12), "停后删录音", self._clean_row, t.text2, line)
        for name, item_box, enabled in self.items[1:]:
            if not _is_segment(name):
                color = t.text2
            elif not enabled:
                color = t.text3
            else:
                color = t.text if _segment_on(name, model) else t.text2
            draw_text(hdc, self.fonts.get(12), labels[name], item_box, color, line | w.DT_CENTER)


def _is_segment(name: str) -> bool:
    return name.startswith("mic_") or name.startswith("clean_")


def _segment_on(name: str, model: PanelModel) -> bool:
    if name.startswith("clean_"):
        return model.auto_clean is not None and (name == "clean_on") == model.auto_clean
    return name == f"mic_{model.mic}"


class ToastView:
    """Layout and drawing of the notification card."""

    MAX_WIDTH = 300
    PAD = 10
    BADGE = 26

    def __init__(self, dpi: int, dark: bool, notice: Notice) -> None:
        self.dpi = dpi
        self.theme = DARK if dark else LIGHT
        self.fonts = Fonts(dpi)
        self.notice = notice
        self.width = 0
        self.height = 0
        self._title_box = (0, 0, 0, 0)
        self._body_box = (0, 0, 0, 0)

    def s(self, px: float) -> int:
        return int(round(px * self.dpi / 96.0))

    def close(self) -> None:
        self.fonts.close()

    def layout(self, hdc) -> tuple[int, int]:
        s = self.s
        pad = s(self.PAD)
        badge = s(self.BADGE)
        text_x = pad + s(2) + badge + s(10)
        max_text = s(self.MAX_WIDTH) - text_x - s(14)
        title_w, title_h = measure_text(hdc, self.fonts.get(13, bold=True), self.notice.title, max_text, wrap=False)
        title_h = max(title_h, s(18))
        body_w = body_h = 0
        if self.notice.body:
            body_w, body_h = measure_text(hdc, self.fonts.get(12), self.notice.body, max_text)
        text_w = max(min(title_w, max_text), body_w, s(110))
        text_h = title_h + (s(2) + body_h if body_h else 0)
        self.height = max(pad * 2 + badge, pad * 2 + text_h)
        self.width = text_x + text_w + s(14)
        top = (self.height - text_h) // 2
        self._title_box = (text_x, top, text_x + text_w, top + title_h)
        self._body_box = (text_x, top + title_h + s(2), text_x + text_w, top + text_h)
        return self.width, self.height

    def paint(self, hdc, rounded: bool = True) -> None:
        self.layout(hdc)
        s = self.s
        t = self.theme
        badge = s(self.BADGE)
        fill_background(hdc, self.width, self.height, t.bg)
        canvas = Canvas(hdc)
        canvas.badge(s(self.PAD) + s(2), (self.height - badge) / 2.0, badge, self.notice.tone)
        canvas.finish()
        if not rounded:
            draw_frame(hdc, self.width, self.height, t.border)
        draw_text(
            hdc, self.fonts.get(13, bold=True), self.notice.title, self._title_box, t.text,
            w.DT_SINGLELINE | w.DT_VCENTER | w.DT_END_ELLIPSIS,
        )
        if self.notice.body:
            draw_text(hdc, self.fonts.get(12), self.notice.body, self._body_box, t.text2, w.DT_WORDBREAK)


def _key(hwnd) -> int:
    return int(hwnd or 0)


_PANELS: dict[int, "PanelWindow"] = {}
_TOASTS: dict[int, "ToastWindow"] = {}


def _route(table):
    def proc(hwnd, msg, wparam, lparam):
        inst = table.get(_key(hwnd))
        if inst is not None:
            try:
                result = inst.dispatch(hwnd, msg, wparam, lparam)
                if result is not None:
                    return result
            except Exception:
                inst.owner._log("ui exception\n" + traceback.format_exc())
        return w.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    return w.WNDPROCTYPE(proc)


_PANEL_PROC = _route(_PANELS)
_TOAST_PROC = _route(_TOASTS)


def _contains(rect, x: int, y: int) -> bool:
    return rect is not None and rect.left <= x < rect.right and rect.top <= y < rect.bottom


def _mouse_xy(lparam: int) -> tuple[int, int]:
    return ctypes.c_short(lparam & 0xFFFF).value, ctypes.c_short((lparam >> 16) & 0xFFFF).value


class PanelWindow:
    """The panel that opens from the tray icon.

    show() runs its own message loop until the panel closes and returns the
    action that closed it: "exit", "settings" or "". Starting and stopping the
    bridge keeps the panel open, so the next step is always in view.
    """

    CLASS_NAME = "KunSoundcoreWorkMicTrayPanel"
    _registered = False

    def __init__(self, owner) -> None:
        self.owner = owner
        self.hwnd = None
        self.cmd = ""
        self.hover = -1
        self.pressed = -1
        self.view: PanelView | None = None
        self.rounded = False
        self.tracking_leave = False
        self._can_dismiss = False
        self._x = 0
        self._edge = 0
        self._grow_up = True
        self._last_elapsed = ""
        self._anchor = None
        self._hook = None
        self._hook_proc = w.HOOKPROC(self._on_mouse)

    def show(self, anchor, cursor) -> str:
        if anchor is not None:
            cx = (anchor.left + anchor.right) // 2
            cy = (anchor.top + anchor.bottom) // 2
        else:
            cx, cy = cursor.x, cursor.y
        work, dpi = w.monitor_at(cx, cy)
        dark = w.system_uses_dark()
        self.view = PanelView(dpi, dark)
        margin = self.view.s(12)
        screen = w.user32.GetDC(None)
        height = self.view.layout(screen, self.owner.panel_model())
        w.user32.ReleaseDC(None, screen)
        width = self.view.width

        self._x = max(work.left + margin, min(cx - width // 2, work.right - width - margin))
        self._grow_up = cy >= (work.top + work.bottom) // 2
        if self._grow_up:
            self._edge = min(anchor.top if anchor is not None else cy, work.bottom) - margin
            pos_y = max(work.top + margin, self._edge - height)
        else:
            self._edge = max(anchor.bottom if anchor is not None else cy, work.top) + margin
            pos_y = self._edge

        if not PanelWindow._registered:
            register_class(self.CLASS_NAME, _PANEL_PROC)
            PanelWindow._registered = True
        self.hwnd = w.user32.CreateWindowExW(
            w.WS_EX_TOOLWINDOW | w.WS_EX_TOPMOST, self.CLASS_NAME, TITLE, w.WS_POPUP,
            self._x, pos_y, width, height, self.owner.hwnd, None, w.kernel32.GetModuleHandleW(None), None,
        )
        if not self.hwnd:
            self._cleanup()
            return ""
        _PANELS[_key(self.hwnd)] = self
        self.rounded = style_window(self.hwnd, self.view.theme, dark)
        self._can_dismiss = False
        w.user32.ShowWindow(self.hwnd, w.SW_SHOW)
        w.user32.UpdateWindow(self.hwnd)
        w.user32.SetWindowPos(
            self.hwnd, w.HWND_TOPMOST, 0, 0, 0, 0, w.SWP_NOSIZE | w.SWP_NOMOVE | w.SWP_SHOWWINDOW
        )
        self.owner._open_menu = self
        self.owner._bring_to_foreground(self.hwnd)
        self._anchor = anchor
        self._hook = w.user32.SetWindowsHookExW(w.WH_MOUSE_LL, self._hook_proc, w.kernel32.GetModuleHandleW(None), 0)
        self.owner._log(f"panel hook={'on' if self._hook else 'failed'} foreground={w.user32.GetForegroundWindow() == self.hwnd}")
        w.user32.SetTimer(self.hwnd, TIMER_TICK, 500, None)
        # Enable click-outside dismiss only after the opening click has settled.
        w.user32.PostMessageW(self.hwnd, WM_ENABLE_DISMISS, 0, 0)

        msg = w.MSG()
        while self.hwnd and w.user32.IsWindow(self.hwnd):
            result = w.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result == 0:  # WM_QUIT for the app
                w.user32.PostQuitMessage(int(msg.wParam))
                self._close()
                break
            if result == -1:
                break
            w.user32.TranslateMessage(ctypes.byref(msg))
            w.user32.DispatchMessageW(ctypes.byref(msg))
        self._cleanup()
        return self.cmd

    def refresh(self) -> None:
        """Redraw after the bridge state changed, resizing if the text needs it."""
        hwnd = self.hwnd
        if not hwnd or self.view is None or not w.user32.IsWindow(hwnd):
            return
        hdc = w.user32.GetDC(hwnd)
        height = self.view.layout(hdc, self.owner.panel_model())
        w.user32.ReleaseDC(hwnd, hdc)
        client = w.RECT()
        w.user32.GetClientRect(hwnd, ctypes.byref(client))
        if height != client.bottom:
            pos_y = self._edge - height if self._grow_up else self._edge
            w.user32.SetWindowPos(
                hwnd, None, self._x, pos_y, self.view.width, height, w.SWP_NOZORDER | w.SWP_NOACTIVATE
            )
        w.user32.InvalidateRect(hwnd, None, False)

    def _on_mouse(self, code, wparam, lparam):
        """Global mouse hook. The panel only closes on deactivation if it
        became the foreground window, which Windows does not always allow, so
        a press anywhere outside the panel closes it too. Presses on the tray
        icon are left to the tray, which toggles the panel itself."""
        try:
            if code >= 0 and wparam in (w.WM_LBUTTONDOWN, w.WM_RBUTTONDOWN, w.WM_MBUTTONDOWN):
                hwnd = self.hwnd
                if hwnd and self._can_dismiss:
                    info = ctypes.cast(ctypes.c_void_p(lparam), ctypes.POINTER(w.MSLLHOOKSTRUCT)).contents
                    x, y = info.pt.x, info.pt.y
                    rect = w.RECT()
                    w.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    if not _contains(rect, x, y) and not _contains(self._anchor, x, y):
                        w.user32.PostMessageW(hwnd, WM_CLICKED_OUTSIDE, 0, 0)
        except Exception:
            pass
        return w.user32.CallNextHookEx(self._hook, code, wparam, lparam)

    def _unhook(self) -> None:
        hook = self._hook
        self._hook = None
        if hook:
            w.user32.UnhookWindowsHookEx(hook)

    def _close(self, cmd: str = "") -> None:
        self._unhook()
        if cmd:
            self.cmd = cmd
        if getattr(self.owner, "_open_menu", None) is self:
            self.owner._open_menu = None
        hwnd = self.hwnd
        self.hwnd = None
        if hwnd and w.user32.IsWindow(hwnd):
            w.user32.KillTimer(hwnd, TIMER_TICK)
            w.user32.DestroyWindow(hwnd)
        # A deactivation is delivered inside GetMessageW without returning
        # from it, so wake the loop in show() or it would wait for the next
        # posted message and swallow it.
        w.user32.PostMessageW(self.owner.hwnd, w.WM_NULL, 0, 0)

    def _cleanup(self) -> None:
        self._unhook()
        if self.view is not None:
            self.view.close()
            self.view = None

    def _enabled(self) -> list[int]:
        return [i for i, (_n, _box, enabled) in enumerate(self.view.items) if enabled]

    def _activate(self, index: int) -> None:
        name, _box, enabled = self.view.items[index]
        if not enabled:
            return
        if name == "primary":
            if self.owner.state == "idle":
                self.owner._start()
            else:
                self.owner._request_stop()
            self.refresh()
        elif name.startswith("mic_"):
            self.owner._switch_mic(name[len("mic_"):])
            self.refresh()
        elif name.startswith("clean_"):
            self.owner._set_auto_clean(name == "clean_on")
            self.refresh()
        else:
            self._close(name)

    def _set_hover(self, hwnd, index: int) -> None:
        if index != self.hover:
            self.hover = index
            w.user32.InvalidateRect(hwnd, None, False)

    def dispatch(self, hwnd, msg, wparam, lparam):
        if self.view is None:
            return None
        if msg in (w.WM_PAINT, w.WM_PRINTCLIENT):
            model = self.owner.panel_model()
            self._last_elapsed = model.elapsed
            paint_buffered(
                hwnd, lambda hdc, _w, h: self.view.paint(hdc, model, self.hover, self.pressed, self.rounded, h)
            )
            return 0
        if msg == w.WM_ERASEBKGND:
            return 1
        if msg == w.WM_MOUSEACTIVATE:
            return w.MA_ACTIVATE
        if msg == w.WM_MOUSEMOVE:
            self._set_hover(hwnd, self.view.item_at(*_mouse_xy(lparam)))
            if not self.tracking_leave:
                tme = w.TRACKMOUSEEVENT()
                tme.cbSize = ctypes.sizeof(w.TRACKMOUSEEVENT)
                tme.dwFlags = w.TME_LEAVE
                tme.hwndTrack = hwnd
                w.user32.TrackMouseEvent(ctypes.byref(tme))
                self.tracking_leave = True
            return 0
        if msg == w.WM_MOUSELEAVE:
            self.tracking_leave = False
            self.pressed = -1
            self._set_hover(hwnd, -1)
            return 0
        if msg == w.WM_LBUTTONDOWN:
            self.pressed = self.view.item_at(*_mouse_xy(lparam))
            self.hover = self.pressed
            w.user32.InvalidateRect(hwnd, None, False)
            return 0
        if msg == w.WM_LBUTTONUP:
            index = self.view.item_at(*_mouse_xy(lparam))
            was_pressed = self.pressed
            self.pressed = -1
            w.user32.InvalidateRect(hwnd, None, False)
            if index >= 0 and index == was_pressed:
                self._activate(index)
            return 0
        if msg == w.WM_KEYDOWN:
            key = wparam & 0xFFFFFFFF
            if key == w.VK_ESCAPE:
                self._close()
                return 0
            if key in (w.VK_DOWN, w.VK_UP, w.VK_TAB):
                enabled = self._enabled()
                if enabled:
                    step = -1 if key == w.VK_UP else 1
                    if self.hover in enabled:
                        index = enabled[(enabled.index(self.hover) + step) % len(enabled)]
                    else:
                        index = enabled[0] if step > 0 else enabled[-1]
                    self._set_hover(hwnd, index)
                return 0
            if key in (w.VK_RETURN, w.VK_SPACE) and 0 <= self.hover < len(self.view.items):
                self._activate(self.hover)
                return 0
            return None
        if msg == w.WM_TIMER:
            if self.owner.panel_model().elapsed != self._last_elapsed:
                w.user32.InvalidateRect(hwnd, None, False)
            return 0
        if msg == WM_ENABLE_DISMISS:
            self._can_dismiss = True
            return 0
        if msg == WM_CLICKED_OUTSIDE:
            if self._can_dismiss:
                self.owner._log("panel close: clicked outside")
                self.owner._ignore_tray_until = time.monotonic() + DISMISS_GUARD_SEC
                self._close()
            return 0
        if msg == w.WM_ACTIVATE:
            if (wparam & 0xFFFF) == w.WA_INACTIVE and self._can_dismiss:
                self._close()
            return 0
        if msg == w.WM_DESTROY:
            _PANELS.pop(_key(hwnd), None)
            # Unblock the modal loop if _close wasn't used.
            if self.hwnd == hwnd:
                self.hwnd = None
            return 0
        return None


class ToastWindow:
    """A notification card above the tray. It never takes the keyboard focus."""

    CLASS_NAME = "KunSoundcoreWorkMicTrayToast"
    _registered = False
    _current: "ToastWindow | None" = None

    def __init__(self, owner) -> None:
        self.owner = owner
        self.hwnd = None
        self.view: ToastView | None = None
        self.rounded = False
        self.alpha = 0

    def show(self, notice: Notice, anchor=None) -> None:
        self.close()
        if not notice.title:
            return
        if anchor is not None:
            work, dpi = w.monitor_at((anchor.left + anchor.right) // 2, (anchor.top + anchor.bottom) // 2)
        else:
            work, dpi = w.monitor_at(0, 0)
        dark = w.system_uses_dark()
        self.view = ToastView(dpi, dark, notice)
        screen = w.user32.GetDC(None)
        width, height = self.view.layout(screen)
        w.user32.ReleaseDC(None, screen)
        margin = self.view.s(12)
        pos_x = max(work.left + margin, work.right - width - margin)
        pos_y = max(work.top + margin, work.bottom - height - margin)

        if not ToastWindow._registered:
            register_class(self.CLASS_NAME, _TOAST_PROC)
            ToastWindow._registered = True
        self.hwnd = w.user32.CreateWindowExW(
            w.WS_EX_TOOLWINDOW | w.WS_EX_TOPMOST | w.WS_EX_NOACTIVATE | w.WS_EX_LAYERED,
            self.CLASS_NAME, TITLE, w.WS_POPUP,
            pos_x, pos_y, width, height, self.owner.hwnd, None, w.kernel32.GetModuleHandleW(None), None,
        )
        if not self.hwnd:
            self._cleanup()
            return
        _TOASTS[_key(self.hwnd)] = self
        ToastWindow._current = self
        self.rounded = style_window(self.hwnd, self.view.theme, dark)
        self.alpha = 0
        w.user32.SetLayeredWindowAttributes(self.hwnd, 0, 0, w.LWA_ALPHA)
        w.user32.ShowWindow(self.hwnd, w.SW_SHOWNOACTIVATE)
        w.user32.SetWindowPos(
            self.hwnd, w.HWND_TOPMOST, 0, 0, 0, 0, w.SWP_NOSIZE | w.SWP_NOMOVE | w.SWP_NOACTIVATE
        )
        w.user32.UpdateWindow(self.hwnd)
        w.user32.SetTimer(self.hwnd, TIMER_FADE_IN, 15, None)

    def close(self) -> None:
        current = ToastWindow._current
        if current is not None and current is not self:
            current._destroy()
        self._destroy()

    def _destroy(self) -> None:
        hwnd = self.hwnd
        self.hwnd = None
        if ToastWindow._current is self:
            ToastWindow._current = None
        if hwnd and w.user32.IsWindow(hwnd):
            for timer in (TIMER_LIFE, TIMER_FADE_IN, TIMER_FADE_OUT):
                w.user32.KillTimer(hwnd, timer)
            w.user32.DestroyWindow(hwnd)
        self._cleanup()

    def _cleanup(self) -> None:
        if self.view is not None:
            self.view.close()
            self.view = None

    def _lifetime_ms(self) -> int:
        notice = self.view.notice
        if notice.tone == "error":
            return 9000
        if notice.tone == "wait":
            return 8000
        return 4500

    def dispatch(self, hwnd, msg, wparam, lparam):
        if msg in (w.WM_PAINT, w.WM_PRINTCLIENT):
            if self.view is None:
                return None
            paint_buffered(hwnd, lambda hdc, _w, _h: self.view.paint(hdc, self.rounded))
            return 0
        if msg == w.WM_ERASEBKGND:
            return 1
        if msg == w.WM_TIMER:
            if self.view is None:
                return 0
            if wparam == TIMER_FADE_IN:
                self.alpha = min(255, self.alpha + 40)
                w.user32.SetLayeredWindowAttributes(hwnd, 0, self.alpha, w.LWA_ALPHA)
                if self.alpha >= 255:
                    w.user32.KillTimer(hwnd, TIMER_FADE_IN)
                    w.user32.SetTimer(hwnd, TIMER_LIFE, self._lifetime_ms(), None)
            elif wparam == TIMER_LIFE:
                w.user32.KillTimer(hwnd, TIMER_LIFE)
                w.user32.SetTimer(hwnd, TIMER_FADE_OUT, 15, None)
            elif wparam == TIMER_FADE_OUT:
                self.alpha = max(0, self.alpha - 40)
                w.user32.SetLayeredWindowAttributes(hwnd, 0, self.alpha, w.LWA_ALPHA)
                if self.alpha <= 0:
                    self._destroy()
            return 0
        if msg in (w.WM_LBUTTONUP, w.WM_RBUTTONUP):
            self._destroy()
            return 0
        if msg == w.WM_DESTROY:
            _TOASTS.pop(_key(hwnd), None)
            if ToastWindow._current is self:
                ToastWindow._current = None
            return 0
        return None


@dataclass(frozen=True)
class RecordingsModel:
    rows: tuple = ()
    listed: bool = False
    busy: bool = False
    # Why nothing can be done right now (bridge running), or "".
    blocked: str = ""
    status: str = ""


class RecordingsView:
    """Layout and drawing of the cleanup window, in pixels of one DPI."""

    WIDTH = 360
    HEIGHT = 452
    PAD = 14
    ROW = 34
    BUTTON = 28
    TOOLS = (("select_all", "全选"), ("select_mic", "选麦克风录的"))

    def __init__(self, dpi: int, dark: bool) -> None:
        self.dpi = dpi
        self.theme = DARK if dark else LIGHT
        self.fonts = Fonts(dpi)
        self.width = self.s(self.WIDTH)
        self.height = self.s(self.HEIGHT)
        self.items: list[tuple[str, tuple[int, int, int, int], bool]] = []
        self.list_box = (0, 0, 0, 0)
        self.visible = 1

    def s(self, px: float) -> int:
        return int(round(px * self.dpi / 96.0))

    def close(self) -> None:
        self.fonts.close()

    def layout(self, model: RecordingsModel, checked: set[int]) -> None:
        s = self.s
        pad = s(self.PAD)
        right = self.width - pad
        button = s(self.BUTTON)
        idle = not model.busy and not model.blocked
        items = [("refresh", (right - s(64), pad, right, pad + button), idle)]
        bottom = self.height - pad
        clean_all = (pad, bottom - button, right, bottom)
        tools_top = clean_all[1] - s(8) - button
        selectable = [row for row in model.rows if not row.open]
        has_mic = any(row.mic for row in selectable)
        left = pad
        for name, label in self.TOOLS:
            width = s(44) if name == "select_all" else s(96)
            enabled = idle and bool(selectable) and (name != "select_mic" or has_mic)
            items.append((name, (left, tools_top, left + width, tools_top + button), enabled))
            left += width + s(6)
        items.append(("delete", (right - s(104), tools_top, right, tools_top + button), idle and bool(checked)))
        items.append(("delete_all", clean_all, idle and bool(selectable)))
        self.items = items
        top = pad + button + s(30)
        self.list_box = (pad, top, right, tools_top - s(10))
        self.visible = max(1, (self.list_box[3] - self.list_box[1] - s(4)) // s(self.ROW))

    def item_at(self, x: int, y: int) -> int:
        for index, (_name, (left, top, right, bottom), _enabled) in enumerate(self.items):
            if left <= x < right and top <= y < bottom:
                return index
        return -1

    def row_at(self, x: int, y: int, scroll: int) -> int:
        left, top, right, bottom = self.list_box
        if not (left <= x < right and top + self.s(2) <= y < bottom):
            return -1
        return scroll + (y - top - self.s(2)) // self.s(self.ROW)

    def label(self, name: str, checked: set[int]) -> str:
        if name == "refresh":
            return "刷新"
        if name == "delete":
            return f"删除所选（{len(checked)}）" if checked else "删除所选"
        if name == "delete_all":
            return "一键清理全部录音"
        return dict(self.TOOLS)[name]

    def paint(self, hdc, model: RecordingsModel, checked: set[int], scroll: int, hover: int, pressed: int, hover_row: int) -> None:
        self.layout(model, checked)
        s = self.s
        t = self.theme
        pad = s(self.PAD)
        line = w.DT_SINGLELINE | w.DT_VCENTER | w.DT_END_ELLIPSIS
        fill_background(hdc, self.width, self.height, t.bg)
        canvas = Canvas(hdc)
        left, top, right, bottom = self.list_box
        canvas.round_rect(left, top, right - left, bottom - top, s(6), fill=t.button, stroke=t.button_border, stroke_width=max(1, s(1)))
        rows = model.rows
        row_h = s(self.ROW)
        shown = rows[scroll : scroll + self.visible]
        y0 = top + s(2)
        box_size = s(16)
        for offset, row in enumerate(shown):
            y = y0 + offset * row_h
            if scroll + offset == hover_row and not row.open and not model.busy and not model.blocked:
                canvas.round_rect(left + s(3), y, right - left - s(6), row_h, s(4), fill=t.hover)
            bx, by = left + s(12), y + (row_h - box_size) / 2.0
            if row.open:
                canvas.round_rect(bx, by, box_size, box_size, s(3), fill=t.track)
            elif row.file_id in checked:
                canvas.round_rect(bx, by, box_size, box_size, s(3), fill=t.accent)
                canvas.round_rect(bx + s(4), by + s(7), s(8), s(2), s(1), fill=t.on_accent)
            else:
                canvas.round_rect(bx, by, box_size, box_size, s(3), fill=t.button, stroke=t.text3, stroke_width=max(1, s(1)))
            if row.mic or row.open:
                tag_w = s(46) if row.mic else s(50)
                tag_x = right - s(12) - tag_w
                tone = TONES["run"] if row.mic else TONES["connect"]
                canvas.round_rect(tag_x, y + (row_h - s(18)) / 2.0, tag_w, s(18), s(9), fill=tone)
        if len(rows) > self.visible:
            track_h = bottom - top - s(8)
            thumb_h = max(s(20), track_h * self.visible // len(rows))
            span = max(1, len(rows) - self.visible)
            thumb_y = top + s(4) + (track_h - thumb_h) * scroll // span
            canvas.round_rect(right - s(6), thumb_y, s(3), thumb_h, s(1.5), fill=t.text3)
        for index, (name, (bl, bt, br, bb), enabled) in enumerate(self.items):
            active = enabled and hover == index
            down = active and pressed == index
            if name in ("delete", "delete_all") and enabled:
                base = TONES["error"] if name == "delete_all" else t.accent
                fill = shade(base, 0.86) if down else shade(base, 0.93) if active else base
                canvas.round_rect(bl, bt, br - bl, bb - bt, s(5), fill=fill)
            elif not enabled:
                canvas.round_rect(bl, bt, br - bl, bb - bt, s(5), fill=t.track)
            else:
                fill = t.button_pressed if down else t.button_hover if active else t.button
                canvas.round_rect(bl, bt, br - bl, bb - bt, s(5), fill=fill, stroke=t.button_border, stroke_width=max(1, s(1)))
        canvas.finish()

        draw_text(hdc, self.fonts.get(15, bold=True), "豆里的录音", (pad, pad, self.width - pad - s(72), pad + s(self.BUTTON)), t.text, line)
        if model.blocked:
            summary, color = model.blocked, TONES["connect"]
        elif model.busy or not model.listed:
            summary, color = model.status or "正在读取…", t.text2
        else:
            summary = model.status or total_label(rows)
            color = t.text2
        summary_top = pad + s(self.BUTTON) + s(4)
        draw_text(hdc, self.fonts.get(12), summary, (pad, summary_top, self.width - pad, summary_top + s(20)), color, line)

        if not shown:
            empty = "豆里没有录音" if model.listed and not model.busy else ("连接录音豆后在这里列出录音" if not model.busy else "")
            draw_text(hdc, self.fonts.get(12), empty, self.list_box, t.text3, line | w.DT_CENTER)
        for offset, row in enumerate(shown):
            y = y0 + offset * row_h
            text_left = left + s(38)
            color = t.text3 if row.open else t.text
            draw_text(hdc, self.fonts.get(13), row.when, (text_left, y, text_left + s(130), y + row_h), color, line)
            draw_text(hdc, self.fonts.get(12), row.length, (text_left + s(130), y, text_left + s(200), y + row_h), t.text2, line)
            if row.mic or row.open:
                tag_w = s(46) if row.mic else s(50)
                tag_x = right - s(12) - tag_w
                label = "麦克风" if row.mic else "正在录"
                draw_text(hdc, self.fonts.get(11), label, (tag_x, y, tag_x + tag_w, y + row_h), 0xFFFFFF, line | w.DT_CENTER)
        for name, box, enabled in self.items:
            if not enabled:
                color = t.text3
            elif name in ("delete", "delete_all"):
                color = 0xFFFFFF if name == "delete_all" else t.on_accent
            else:
                color = t.text
            draw_text(hdc, self.fonts.get(12 if name != "delete_all" else 13), self.label(name, checked), box, color, line | w.DT_CENTER)


_RECORDINGS: dict[int, "RecordingsWindow"] = {}
_RECORDINGS_PROC = _route(_RECORDINGS)


class RecordingsWindow:
    """A normal window that lists the recordings on the bean and deletes the
    chosen ones. The owner runs the Bluetooth work; this only draws its state
    and asks before anything is deleted."""

    CLASS_NAME = "KunSoundcoreWorkMicRecordings"
    STYLE = w.WS_CAPTION | w.WS_SYSMENU | w.WS_MINIMIZEBOX
    _registered = False

    def __init__(self, owner) -> None:
        self.owner = owner
        self.hwnd = None
        self.view: RecordingsView | None = None
        self.checked: set[int] = set()
        self.scroll = 0
        self.hover = -1
        self.pressed = -1
        self.hover_row = -1
        self.tracking_leave = False

    def show(self) -> None:
        if self.hwnd and w.user32.IsWindow(self.hwnd):
            if w.user32.IsIconic(self.hwnd):
                w.user32.ShowWindow(self.hwnd, w.SW_RESTORE)
            self.owner._bring_to_foreground(self.hwnd)
            return
        pt = w.POINT()
        w.user32.GetCursorPos(ctypes.byref(pt))
        work, dpi = w.monitor_at(pt.x, pt.y)
        dark = w.system_uses_dark()
        self.view = RecordingsView(dpi, dark)
        frame = w.RECT(0, 0, self.view.width, self.view.height)
        w.user32.AdjustWindowRectEx(ctypes.byref(frame), self.STYLE, False, 0)
        width, height = frame.right - frame.left, frame.bottom - frame.top
        x = max(work.left, (work.left + work.right - width) // 2)
        y = max(work.top, (work.top + work.bottom - height) // 2)
        if not RecordingsWindow._registered:
            register_class(self.CLASS_NAME, _RECORDINGS_PROC, shadow=False, icon=self.owner.icons.get("idle"))
            RecordingsWindow._registered = True
        self.hwnd = w.user32.CreateWindowExW(
            0, self.CLASS_NAME, f"整理录音 · {TITLE}", self.STYLE,
            x, y, width, height, None, None, w.kernel32.GetModuleHandleW(None), None,
        )
        if not self.hwnd:
            self._cleanup()
            return
        _RECORDINGS[_key(self.hwnd)] = self
        w.dwm_set(self.hwnd, w.DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
        w.user32.ShowWindow(self.hwnd, w.SW_SHOW)
        w.user32.UpdateWindow(self.hwnd)
        self.owner._bring_to_foreground(self.hwnd)

    @property
    def is_shown(self) -> bool:
        return bool(self.hwnd) and bool(w.user32.IsWindow(self.hwnd))

    def refresh(self) -> None:
        if not self.is_shown or self.view is None:
            return
        model = self.owner.recordings_model()
        selectable = {row.file_id for row in model.rows if not row.open}
        self.checked &= selectable
        self.scroll = max(0, min(self.scroll, len(model.rows) - self.view.visible))
        w.user32.InvalidateRect(self.hwnd, None, False)

    def close(self) -> None:
        hwnd = self.hwnd
        if hwnd and w.user32.IsWindow(hwnd):
            w.user32.DestroyWindow(hwnd)

    def _cleanup(self) -> None:
        if self.view is not None:
            self.view.close()
            self.view = None

    def _confirm(self, text: str) -> bool:
        flags = w.MB_YESNO | w.MB_ICONWARNING | w.MB_DEFBUTTON2
        return w.user32.MessageBoxW(self.hwnd, text, "删除录音", flags) == w.IDYES

    def _activate(self, name: str) -> None:
        model = self.owner.recordings_model()
        rows = [row for row in model.rows if not row.open]
        if name == "refresh":
            self.owner.recordings_refresh()
        elif name == "select_all":
            ids = {row.file_id for row in rows}
            self.checked = set() if ids and ids <= self.checked else ids
        elif name == "select_mic":
            self.checked = {row.file_id for row in rows if row.mic}
        elif name == "delete":
            chosen = [row for row in rows if row.file_id in self.checked]
            if chosen and self._confirm(delete_prompt(chosen, everything=False)):
                self.owner.recordings_delete([row.file_id for row in chosen])
                self.checked.clear()
        elif name == "delete_all":
            if rows and self._confirm(delete_prompt(rows, everything=True)):
                self.owner.recordings_delete([row.file_id for row in rows])
                self.checked.clear()
        w.user32.InvalidateRect(self.hwnd, None, False)

    def _toggle_row(self, index: int) -> None:
        model = self.owner.recordings_model()
        if model.busy or model.blocked or not (0 <= index < len(model.rows)):
            return
        row = model.rows[index]
        if row.open:
            return
        self.checked ^= {row.file_id}
        w.user32.InvalidateRect(self.hwnd, None, False)

    def _scroll_by(self, rows: int) -> None:
        count = len(self.owner.recordings_model().rows)
        top = max(0, count - self.view.visible)
        value = max(0, min(top, self.scroll + rows))
        if value != self.scroll:
            self.scroll = value
            w.user32.InvalidateRect(self.hwnd, None, False)

    def dispatch(self, hwnd, msg, wparam, lparam):
        if self.view is None:
            return None
        if msg in (w.WM_PAINT, w.WM_PRINTCLIENT):
            model = self.owner.recordings_model()
            paint_buffered(
                hwnd,
                lambda hdc, _w, _h: self.view.paint(
                    hdc, model, self.checked, self.scroll, self.hover, self.pressed, self.hover_row
                ),
            )
            return 0
        if msg == w.WM_ERASEBKGND:
            return 1
        if msg == w.WM_MOUSEMOVE:
            x, y = _mouse_xy(lparam)
            index = self.view.item_at(x, y)
            row = self.view.row_at(x, y, self.scroll)
            if index != self.hover or row != self.hover_row:
                self.hover, self.hover_row = index, row
                w.user32.InvalidateRect(hwnd, None, False)
            if not self.tracking_leave:
                tme = w.TRACKMOUSEEVENT()
                tme.cbSize = ctypes.sizeof(w.TRACKMOUSEEVENT)
                tme.dwFlags = w.TME_LEAVE
                tme.hwndTrack = hwnd
                w.user32.TrackMouseEvent(ctypes.byref(tme))
                self.tracking_leave = True
            return 0
        if msg == w.WM_MOUSELEAVE:
            self.tracking_leave = False
            self.hover = self.pressed = self.hover_row = -1
            w.user32.InvalidateRect(hwnd, None, False)
            return 0
        if msg == w.WM_LBUTTONDOWN:
            x, y = _mouse_xy(lparam)
            self.pressed = self.view.item_at(x, y)
            if self.pressed < 0:
                self._toggle_row(self.view.row_at(x, y, self.scroll))
            w.user32.InvalidateRect(hwnd, None, False)
            return 0
        if msg == w.WM_LBUTTONUP:
            index = self.view.item_at(*_mouse_xy(lparam))
            was_pressed = self.pressed
            self.pressed = -1
            w.user32.InvalidateRect(hwnd, None, False)
            if index >= 0 and index == was_pressed:
                name, _box, enabled = self.view.items[index]
                if enabled:
                    self._activate(name)
            return 0
        if msg == w.WM_MOUSEWHEEL:
            delta = ctypes.c_short((wparam >> 16) & 0xFFFF).value
            self._scroll_by(-3 if delta > 0 else 3)
            return 0
        if msg == w.WM_KEYDOWN:
            key = wparam & 0xFFFFFFFF
            if key == w.VK_ESCAPE:
                self.close()
                return 0
            steps = {w.VK_UP: -1, w.VK_DOWN: 1, w.VK_PRIOR: -self.view.visible, w.VK_NEXT: self.view.visible}
            if key in steps:
                self._scroll_by(steps[key])
                return 0
            return None
        if msg == w.WM_CLOSE:
            self.close()
            return 0
        if msg == w.WM_DESTROY:
            _RECORDINGS.pop(_key(hwnd), None)
            if self.hwnd == hwnd:
                self.hwnd = None
            self._cleanup()
            return 0
        return None
