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

from soundcore_diag.tray_model import GLYPHS, TONES  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SS = 8  # supersampling factor
WHITE = (255, 255, 255, 255)
APP_TOP = (0x4F, 0x83, 0xFF)
APP_BOTTOM = (0x24, 0x4C, 0xE0)
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


def badge(tone: str, size: int) -> Image.Image:
    big = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    draw.ellipse((0, 0, size * SS - 1, size * SS - 1), fill=_rgb(TONES[tone]))
    _glyph(draw, tone, size, (0, 0, size), WHITE)
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
    if size < 32:
        _glyph(draw, "run", size, (0, 0, size), WHITE)
    else:
        disc = round(size * 0.60)
        offset = (size - disc) / 2
        draw.ellipse((offset * SS, offset * SS, (offset + disc) * SS - 1, (offset + disc) * SS - 1), fill=WHITE)
        _glyph(draw, "run", size, (offset, offset, disc), APP_BOTTOM + (255,))
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
