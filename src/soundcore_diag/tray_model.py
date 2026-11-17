"""What the tray shows for each bridge state and status message.

This module has no Windows dependency. The bridge reports progress as plain
sentences; everything the user reads in the tray panel, the tooltip and the
notification card is derived from them here, so the wording lives in one
place. Nothing in this module ever carries a Bluetooth address.
"""

from __future__ import annotations

from dataclasses import dataclass

TITLE = "录音豆麦克风"

# Tone colours as 0xRRGGBB. The tray icons are drawn from the same values.
TONES = {
    "idle": 0x7B8494,
    "connect": 0xF59F0A,
    "wait": 0x3B82F6,
    "run": 0x1FAA59,
    "error": 0xE5484D,
}

# The badge is the bean seen from the front, in a unit square: a round body,
# and the clip sticking out above it in a darker shade of the same tone.
# BEAN_BODY is (cx, cy, radius); BEAN_CLIP is (cx, top, width, height, corner).
BEAN_BODY = (0.50, 0.585, 0.415)
BEAN_CLIP = (0.50, 0.0, 0.36, 0.40, 0.10)
CLIP_SHADE = 0.72


def shade(rgb: int, factor: float) -> int:
    r, g, b = (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF
    return (int(r * factor) << 16) | (int(g * factor) << 8) | int(b * factor)


# Glyphs drawn in white on the bean body, in a unit square that is mapped
# onto the body's bounding box.
# ("bar", cx, cy, width, height) is a capsule; ("dot", cx, cy, radius) a circle.
GLYPHS = {
    "idle": (("bar", 0.50, 0.50, 0.44, 0.12),),
    "connect": (("dot", 0.29, 0.50, 0.075), ("dot", 0.50, 0.50, 0.075), ("dot", 0.71, 0.50, 0.075)),
    "wait": (("dot", 0.50, 0.50, 0.20),),
    "run": (
        ("bar", 0.29, 0.50, 0.13, 0.28),
        ("bar", 0.50, 0.50, 0.13, 0.52),
        ("bar", 0.71, 0.50, 0.13, 0.36),
    ),
    "error": (("bar", 0.50, 0.42, 0.13, 0.34), ("dot", 0.50, 0.73, 0.075)),
}

STEPS = ("连接", "按录音键", "传声")


@dataclass(frozen=True)
class StateView:
    tone: str
    headline: str
    hint: str
    step: int
    button: str
    button_primary: bool
    button_enabled: bool = True


STATE_VIEWS = {
    "idle": StateView(
        "idle", "未连接", "先断开手机上的连接，把录音豆放在电脑旁边。", 0, "开始桥接", True
    ),
    "starting": StateView(
        "connect", "正在连接…", "正在寻找并连接录音豆，通常只要几秒。", 1, "取消", False
    ),
    "waiting": StateView(
        "wait", "请按录音键", "按一下豆上的录音键，灯变色后就可以说话。", 2, "停止桥接", False
    ),
    "running": StateView(
        "run", "正在传声", "把软件里的麦克风选成 CABLE Output。", 3, "停止桥接", False
    ),
    "stopping": StateView("connect", "正在停止…", "正在断开，请稍等。", 0, "正在停止…", False, False),
}


def state_view(state: str) -> StateView:
    return STATE_VIEWS.get(state, STATE_VIEWS["idle"])


def tooltip(state: str) -> str:
    return f"{TITLE} · {state_view(state).headline}"


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


@dataclass(frozen=True)
class Notice:
    """One status message, ready to show.

    state  -- bridge state this message implies, or None.
    tone   -- colour and glyph of the badge.
    toast  -- show a notification card (when the panel is not open).
    sticky -- keep it in the panel after the bridge has gone back to idle.
    """

    tone: str
    title: str
    body: str = ""
    state: str | None = None
    toast: bool = False
    sticky: bool = False


STARTED = Notice("idle", f"{TITLE}已就绪", "它在任务栏右下角，点一下图标就能开始。", toast=True)
BUSY = Notice("connect", "已经在桥接了", "要停下来，请点图标后选「停止桥接」。", toast=True)
NOT_RUNNING = Notice("idle", "现在没有在桥接", toast=True)
CRASHED = "桥接出错，已停止。"


def _reason(message: str) -> str:
    start = message.find("（")
    end = message.find("）", start + 1)
    if start < 0 or end < 0:
        return ""
    return message[start + 1 : end].strip()


def _error(title: str, body: str = "") -> Notice:
    return Notice("error", title, body, toast=True, sticky=True)


def interpret(message: str) -> Notice:
    """Map one bridge status sentence to what the tray shows."""
    text = " ".join(message.split())

    # Progress. Only the two steps the user has to act on get a card; the
    # rest is carried by the icon, the tooltip and the panel.
    if "正在传输声音" in text:
        return Notice(
            "run", "正在传声", "把软件里的麦克风选成 CABLE Output。", state="running", toast=True
        )
    if text.startswith("录音已暂停"):
        return Notice(
            "wait",
            "录音已暂停",
            "连接还在。再按一下豆上的录音键，就会接着传声。",
            state="waiting",
            toast=True,
        )
    if "请按下录音豆" in text or "已连上" in text:
        return Notice(
            "wait",
            "已连上，请按录音键",
            "按一下豆上的录音键，灯变色后就可以说话。",
            state="waiting",
            toast=True,
        )
    if any(token in text for token in ("正在扫描", "正在连接", "正在打开", "虚拟声卡已打开")):
        return Notice("connect", "", state="starting")
    if "正在开始桥接" in text or "正在停止桥接" in text:
        return Notice("connect", "")
    if text.startswith("已取消"):
        return Notice("idle", "")

    # The bridge ended.
    if text.startswith("桥接已停止。"):
        return Notice(
            "idle", "已停止桥接", "再按一下豆上的键，把豆上的录音也停掉。", toast=True, sticky=True
        )
    if text.startswith("桥接已结束"):
        reason = _reason(text)
        lead = f"{reason}。" if reason else ""
        return Notice(
            "idle", "桥接已结束", f"{lead}再按一下豆上的键，把豆上的录音也停掉。", toast=True, sticky=True
        )
    if text.startswith("桥接已停止"):
        reason = _reason(text)
        lead = f"{reason}。" if reason else ""
        return _error("桥接中断了", f"{lead}再按一下豆上的键，把豆上的录音也停掉。")

    # Failures.
    if "没有找到录音豆" in text:
        return _error("没找到录音豆", "靠近电脑，断开手机上的连接，再试一次。")
    if "没有等到录音开始" in text:
        return _error("没等到录音开始", "豆若已在录音，先按一下停掉，再按一次。")
    if "没有收到声音" in text:
        return _error("没有收到声音", "确认豆上已经开始录音，再试一次。")
    if "连接或传输失败" in text:
        return _error("连接失败", "没连上或传输中断，请再点一次「开始桥接」。")
    if "设备特征不匹配" in text:
        return _error("设备不匹配", "已断开，没有发送任何录音控制。")
    if "解码器不可用" in text:
        return _error("解码器不可用", "没有打开蓝牙。请重新运行一次安装脚本。")
    if "SD_ENABLE_ASIO" in text:
        return _error("请先删掉 SD_ENABLE_ASIO", "检测到这个环境变量，没有打开声卡。删掉后重新启动。")
    if "找到多个标准 CABLE Input" in text:
        return _error("有多个 CABLE Input", "没有自动挑选。请只保留官方标准版 VB-CABLE。")
    if "没有找到标准 VB-CABLE" in text:
        return _error("还没装好 VB-CABLE", "请安装官方标准版 VB-CABLE，装完重启电脑。")
    if "CABLE Input" in text or "播放设备" in text:
        return _error("虚拟声卡打不开", text)
    if text.startswith("桥接出错"):
        return _error("桥接出错", "已停止。详细信息记在 tray.log 里。")

    if any(token in text for token in ("失败", "无法", "没有找到", "没有等到", "没有收到")):
        return _error("桥接已停止", text)
    return Notice("idle", "提示", text, toast=bool(text))
