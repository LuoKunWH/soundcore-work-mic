"""Optional 16 kHz bridge to the standard VB-CABLE playback endpoint.

This module does not import PortAudio until a cable sink is actually opened.
It never changes the system default playback or recording device, and it never
installs a driver. Only the standard virtual cable is accepted: the playback
endpoint whose name starts with "CABLE Input". "CABLE Output" is the recording
endpoint other applications should select. A+B, C+D, Hi-Fi Cable, and ASIO are
not used.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

OFFICIAL_URL = "https://vb-audio.com/Cable/"
PACK_NAME = "VBCABLE_Driver_Pack46.zip"
SAMPLE_RATE = 16000

MISSING_TEXT = (
    "没有找到标准 VB-CABLE 的播放端 “CABLE Input”。\n"
    "本程序不会安装驱动，也不会修改系统默认扬声器或麦克风。\n"
    "请只安装官方标准包，不要使用 A+B 或 C+D：\n"
    f"{OFFICIAL_URL}\n"
    f"厂商页面当前列出的 Windows 包是 {PACK_NAME}（2026 年 11 月）。\n"
    "厂商安装步骤：解压全部文件，以管理员身份运行安装程序，安装或卸载后重启。\n"
    "其他程序把麦克风选成 “CABLE Output”。本程序只向 “CABLE Input” 写入。"
)


class CableMissing(Exception):
    def __init__(self, message: str = MISSING_TEXT) -> None:
        super().__init__(message)


class CableUnavailable(Exception):
    pass


@dataclass(frozen=True)
class OutputDevice:
    index: int
    name: str
    hostapi: str
    max_output_channels: int


@dataclass(frozen=True)
class CableSelection:
    index: int
    name: str
    hostapi: str
    channels: int


def is_standard_cable_input(name: str) -> bool:
    folded = " ".join(name.lower().replace("(", " ").replace(")", " ").split())
    if not folded.startswith("cable input"):
        return False
    if "cable output" in folded:
        return False
    banned = ("cable a", "cable b", "cable c", "cable d", "hi-fi", "hifi", "asio")
    return not any(token in folded for token in banned)


def is_standard_cable_output(name: str) -> bool:
    folded = " ".join(name.lower().replace("(", " ").replace(")", " ").split())
    if not folded.startswith("cable output"):
        return False
    banned = ("cable a", "cable b", "cable c", "cable d", "hi-fi", "hifi", "asio")
    return not any(token in folded for token in banned)


def select_cable_input(devices: list[OutputDevice]) -> CableSelection:
    matches = []
    for device in devices:
        if device.max_output_channels < 1:
            continue
        if "asio" in device.hostapi.lower():
            continue
        if not is_standard_cable_input(device.name):
            continue
        matches.append(device)
    wasapi = [device for device in matches if "wasapi" in device.hostapi.lower()]
    pool = wasapi or matches
    if not pool:
        raise CableMissing(MISSING_TEXT)
    if len(pool) != 1:
        raise CableMissing("找到多个标准 CABLE Input 播放端，没有自动挑选。\n" + MISSING_TEXT)
    chosen = pool[0]
    channels = 2 if chosen.max_output_channels >= 2 else 1
    return CableSelection(chosen.index, chosen.name, chosen.hostapi, channels)


def expand_pcm(mono: bytes, channels: int) -> bytes:
    if channels not in (1, 2):
        raise CableUnavailable("CABLE Input 只接受单声道或双声道")
    if len(mono) % 2:
        mono = mono[:-1]
    if channels == 1:
        return mono
    frames = len(mono) // 2
    out = bytearray(frames * 4)
    for index in range(frames):
        sample = mono[2 * index : 2 * index + 2]
        start = 4 * index
        out[start : start + 2] = sample
        out[start + 2 : start + 4] = sample
    return bytes(out)


def query_output_devices() -> list[OutputDevice]:
    if os.environ.get("SD_ENABLE_ASIO"):
        raise CableUnavailable(
            "检测到 SD_ENABLE_ASIO。本程序不加载 ASIO 版 PortAudio，也没有打开声卡。"
        )
    import sounddevice as sd

    hostapis = sd.query_hostapis()
    rows = []
    for index, device in enumerate(sd.query_devices()):
        host = hostapis[int(device["hostapi"])]["name"]
        rows.append(
            OutputDevice(
                index=index,
                name=str(device["name"]),
                hostapi=str(host),
                max_output_channels=int(device["max_output_channels"]),
            )
        )
    return rows


class CableSink:
    """Writes 16 kHz PCM16 to one already-selected playback device."""

    def __init__(self, selection: CableSelection) -> None:
        if os.environ.get("SD_ENABLE_ASIO"):
            raise CableUnavailable(
                "检测到 SD_ENABLE_ASIO。本程序不加载 ASIO 版 PortAudio，也没有打开声卡。"
            )
        import sounddevice as sd

        self.channels = selection.channels
        self.name = selection.name
        self.hostapi = selection.hostapi
        try:
            self._stream = sd.RawOutputStream(
                samplerate=SAMPLE_RATE,
                channels=selection.channels,
                dtype="int16",
                device=selection.index,
                blocksize=0,
                dither_off=True,
                latency="low",
            )
            self._stream.start()
        except Exception as exc:
            raise CableUnavailable(
                "无法以 16000 Hz 打开 CABLE Input。"
                "没有改用其他采样率，也没有修改系统默认设备。"
                f"（{type(exc).__name__}）"
            ) from None

    def write(self, mono_pcm: bytes) -> None:
        payload = expand_pcm(mono_pcm, self.channels)
        if not payload:
            return
        try:
            self._stream.write(payload)
        except Exception as exc:
            raise CableUnavailable(f"写入 CABLE Input 失败（{type(exc).__name__}）") from None

    def close(self) -> None:
        stream = getattr(self, "_stream", None)
        if stream is None:
            return
        self._stream = None
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass


def _hostapi_rank(hostapi: str) -> int:
    name = hostapi.lower()
    if "wasapi" in name:
        return 0
    if name == "mme" or name.endswith(" mme") or name.startswith("mme"):
        return 1
    if "directsound" in name:
        return 2
    return 9


def _hostapi_token(hostapi: str) -> str:
    name = hostapi.lower()
    if "wasapi" in name:
        return "wasapi"
    if "directsound" in name:
        return "directsound"
    if "mme" in name:
        return "mme"
    return name


def _standard_cable_candidates(devices: list[OutputDevice]) -> list[OutputDevice]:
    matches = []
    for device in devices:
        if device.max_output_channels < 1:
            continue
        if "asio" in device.hostapi.lower():
            continue
        if not is_standard_cable_input(device.name):
            continue
        matches.append(device)
    if not matches:
        raise CableMissing(MISSING_TEXT)
    seen: set[str] = set()
    candidates: list[OutputDevice] = []
    for device in sorted(matches, key=lambda item: (_hostapi_rank(item.hostapi), item.index)):
        token = _hostapi_token(device.hostapi)
        if token in seen:
            continue
        seen.add(token)
        candidates.append(device)
    return candidates


def open_cable_input() -> CableSink:
    try:
        devices = query_output_devices()
        candidates = _standard_cable_candidates(devices)
    except CableMissing:
        raise
    except CableUnavailable:
        raise
    except Exception as exc:
        raise CableUnavailable(
            f"读取播放设备失败（{type(exc).__name__}）。没有修改系统默认设备。"
        ) from None
    last_error: Exception | None = None
    for device in candidates:
        selection = CableSelection(
            device.index,
            device.name,
            device.hostapi,
            2 if device.max_output_channels >= 2 else 1,
        )
        try:
            sink = CableSink(selection)
        except CableUnavailable as exc:
            last_error = exc
            print(
                f"{selection.hostapi} 无法以 16000 Hz 打开 CABLE Input，改试其他接口。"
                "没有改用其他采样率，也没有修改系统默认设备。"
            )
            continue
        print(
            f"已打开 {selection.name}（{selection.hostapi}，"
            f"{selection.channels} 声道，16000 Hz）。未修改系统默认设备。"
        )
        return sink
    if last_error is not None:
        raise last_error
    raise CableUnavailable("无法以 16000 Hz 打开 CABLE Input。没有改用其他采样率，也没有修改系统默认设备。")
