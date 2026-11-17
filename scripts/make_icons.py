"""Draw the tray icons, the app icon and the README state strip.

Developer tool, not needed to run the program. It needs Pillow:

    python -m pip install pillow
    python scripts/make_icons.py

The shapes and colours come from soundcore_diag.tray_model, so the icon files
and the badges drawn inside the tray panel stay the same drawing.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soundcore_diag.tray_model import BEAN_BODY, BEAN_CLIP, CLIP_SHADE, GLYPHS, TONES, shade  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SS = 8  # supersampling factor
WHITE = (255, 255, 255, 255)
APP_TOP = (0x4F, 0x83, 0xFF)
APP_BOTTOM = (0x24, 0x4C, 0xE0)
APP_CLIP = (0xD3, 0xDD, 0xF2, 255)
APP_GRILLE = (0xC4, 0xCB, 0xD8, 255)
LABELS = (("idle", "未连接"), ("connect", "正在连接"), ("wait", "请按录音键"), ("run", "正在传声"))
CJK_FONTS = (
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)


def _rgb(value: int) -> tuple[int, int, int, int]:
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF, 255)


def _glyph(draw: ImageDraw.ImageDraw, tone: str, size: int, box: tuple[float, float, float], fill) -> None:
    """Draw a glyph into the square (x, y, side), given in final pixels.

    At small sizes the edges are snapped to whole pixels so that bars and
    dots stay crisp in the notification area.
    """
    x0, y0, side = box
    snap = size <= 32

    def px(value: float) -> float:
        return round(value) if snap else value

    for shape in GLYPHS[tone]:
        if shape[0] == "bar":
            _kind, cx, cy, width, height = shape
            w = max(2, px(width * side)) if snap else width * side
            h = max(2, px(height * side)) if snap else height * side
            left = px(x0 + cx * side - w / 2)
            top = px(y0 + cy * side - h / 2)
            radius = min(w, h) / 2
            draw.rounded_rectangle(
                (left * SS, top * SS, (left + w) * SS - 1, (top + h) * SS - 1), radius=radius * SS, fill=fill
            )
        else:
            _kind, cx, cy, radius = shape
            d = max(2, px(radius * 2 * side)) if snap else radius * 2 * side
            left = px(x0 + cx * side - d / 2)
            top = px(y0 + cy * side - d / 2)
            draw.ellipse((left * SS, top * SS, (left + d) * SS - 1, (top + d) * SS - 1), fill=fill)


def _same_parity(value: float, side: int) -> int:
    """value rounded to an integer that centres on a side of `side` pixels."""
    whole = round(value)
    return whole if (side - whole) % 2 == 0 else whole + (1 if value > whole else -1)


def _bean(
    draw: ImageDraw.ImageDraw, size: int, origin: tuple[float, float], side: int, body_fill, clip_fill
) -> tuple[float, float, float]:
    """Draw the bean filling the square of `side` pixels at `origin`.

    Returns the body's bounding square (x, y, side) for the glyph.
    """
    clip_cx, clip_top, clip_w, clip_h, clip_r = BEAN_CLIP
    body_cx, body_cy, body_r = BEAN_BODY
    if size <= 32:
        d = _same_parity(body_r * 2 * side, side)
        cw = _same_parity(clip_w * side, side)
        ch = round(clip_h * side)
    else:
        d, cw, ch = body_r * 2 * side, clip_w * side, clip_h * side
    x0, y0 = origin
    left = x0 + body_cx * side - d / 2
    top = y0 + round((body_cy + body_r) * side) - d
    clip_left = x0 + clip_cx * side - cw / 2
    clip_y = y0 + clip_top * side
    draw.rounded_rectangle(
        (clip_left * SS, clip_y * SS, (clip_left + cw) * SS - 1, (clip_y + ch) * SS - 1),
        radius=clip_r * side * SS, fill=clip_fill,
    )
    draw.ellipse((left * SS, top * SS, (left + d) * SS - 1, (top + d) * SS - 1), fill=body_fill)
    return left, top, d


def badge(tone: str, size: int) -> Image.Image:
    big = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    rgb = TONES[tone]
    body = _bean(draw, size, (0, 0), size, _rgb(rgb), _rgb(shade(rgb, CLIP_SHADE)))
    _glyph(draw, tone, size, body, WHITE)
    return big.resize((size, size), Image.LANCZOS)


def app_icon(size: int) -> Image.Image:
    """A blue tile holding the white bean with the sound bars."""
    full = size * SS
    gradient = Image.new("RGBA", (full, full))
    pixels = ImageDraw.Draw(gradient)
    for row in range(full):
        t = row / max(1, full - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(APP_TOP, APP_BOTTOM)) + (255,)
        pixels.line((0, row, full, row), fill=color)
    mask = Image.new("L", (full, full), 0)
    inset = 0 if size <= 24 else round(size * 0.04) * SS
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset, inset, full - 1 - inset, full - 1 - inset), radius=round(full * 0.225), fill=255
    )
    big = Image.new("RGBA", (full, full), (0, 0, 0, 0))
    big.paste(gradient, (0, 0), mask)
    draw = ImageDraw.Draw(big)
    side = round(size * (0.80 if size < 32 else 0.68))
    offset = (size - side) / 2
    if size <= 32:
        offset = round(offset)
    body = _bean(draw, size, (offset, offset), side, WHITE, APP_CLIP)
    if size >= 24:
        _glyph(draw, "run", size, body, APP_BOTTOM + (255,))
    if size >= 48:
        x, y, d = body
        for cy in (0.12, 0.88):
            gw, gh = d * 0.20, d * 0.05
            gx, gy = x + d / 2 - gw / 2, y + d * cy - gh / 2
            draw.rounded_rectangle(
                (gx * SS, gy * SS, (gx + gw) * SS - 1, (gy + gh) * SS - 1), radius=gh / 2 * SS, fill=APP_GRILLE
            )
    return big.resize((size, size), Image.LANCZOS)


def save_ico(path: Path, render) -> None:
    images = [render(size) for size in SIZES]
    images[-1].save(path, format="ICO", sizes=[(s, s) for s in SIZES], append_images=images[:-1])


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in CJK_FONTS:
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    raise SystemExit("没有找到可用的中文字体，无法生成说明图。")


def state_strip(path: Path) -> None:
    scale = 2
    cell, icon, pad = 150 * scale, 56 * scale, 28 * scale
    width, height = cell * len(LABELS) + pad * 2, 150 * scale
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=16 * scale, fill=(0xF4, 0xF5, 0xF7, 255))
    font = _font(15 * scale)
    for index, (tone, label) in enumerate(LABELS):
        center = pad + cell * index + cell // 2
        image.alpha_composite(badge(tone, icon), (center - icon // 2, 32 * scale))
        draw.text((center, 112 * scale), label, font=font, fill=(0x1A, 0x1A, 0x1A, 255), anchor="mm")
    image.save(path)


def main() -> int:
    icons = ROOT / "tray_icons"
    for tone, name in (("idle", "tray-idle"), ("connect", "tray-connect"), ("wait", "tray-wait"), ("run", "tray-run")):
        save_ico(icons / f"{name}.ico", lambda size, tone=tone: badge(tone, size))
    save_ico(icons / "app.ico", app_icon)
    state_strip(ROOT / "docs" / "images" / "tray-states.png")
    print("图标已生成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
