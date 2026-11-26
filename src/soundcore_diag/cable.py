"""Bridge 16 kHz PCM to the standard VB-CABLE playback endpoint.

This module does not import PortAudio until a cable sink is actually opened.
It never changes the system default playback or recording device, and it never
installs a driver. Only the standard virtual cable is accepted: the playback
endpoint whose name starts with "CABLE Input". "CABLE Output" is the recording
endpoint other applications should select. "CABLE In 16ch" is not that
endpoint. A+B, C+D, Hi-Fi Cable, and ASIO are not used.

The bean's PCM is 16 kHz. VB-CABLE's Windows mix format is usually 44100 or
48000 Hz. PortAudio's WASAPI shared mode only asks Windows to convert when
paWinWasapiAutoConvert is set; without it a 16 kHz client can fail to open,
or open and then never render, so both cable meters stay at zero. The sink
therefore opens at the endpoint's current rate (and retries 16000 Hz), turns
autoconvert on for WASAPI shared mode, and plays from a callback. The
callback runs on PortAudio's thread. The Bluetooth thread only queues PCM, so
a stuck driver cannot freeze the bridge inside a blocking write.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

OFFICIAL_URL = "https://vb-audio.com/Cable/"
PACK_NAME = "VBCABLE_Driver_Pack46.zip"
SAMPLE_RATE = 16000
_MIN_RATE = 8000
_MAX_RATE = 192000
# One second is enough slack for a BLE burst. Anything older is dropped so a
# stream that is not pulling cannot grow without bound.
_QUEUE_SECONDS = 1.0
# The stream is started before the bean is connected. If the callback has
# still never run by the time PCM arrives, the endpoint is not rendering.
_CALLBACK_GRACE_SECONDS = 0.75

MISSING_TEXT = (
    "没有找到标准 VB-CABLE 的播放端 “CABLE Input”。\n"
    "本程序不会安装驱动，也不会修改系统默认扬声器或麦克风。\n"
    "请只安装官方标准包，不要使用 A+B 或 C+D：\n"
    f"{OFFICIAL_URL}\n"
    f"厂商页面当前列出的 Windows 包是 {PACK_NAME}（2026 年 11 月）。\n"
    "厂商安装步骤：解压全部文件，以管理员身份运行安装程序，安装或卸载后重启。\n"
    "其他程序把麦克风选成 “CABLE Output”。本程序只向 “CABLE Input” 写入。"
)

OPEN_FAILED = (
    "无法打开 CABLE Input。"
    "已尝试该播放端当前的采样率和 16000 Hz，没有修改系统默认设备。"
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
    default_samplerate: int = 0


@dataclass(frozen=True)
class CableSelection:
    index: int
    name: str
    hostapi: str
    channels: int
    default_samplerate: int = 0


def is_standard_cable_input(name: str) -> bool:
    folded = " ".join(name.lower().replace("(", " ").replace(")", " ").split())
    if not folded.startswith("cable input"):
        return False
    if "cable output" in folded:
        return False
    banned = ("cable a", "cable b", "cable c", "cable d", "hi-fi", "hifi", "asio", "16ch", "16 ch")
    return not any(token in folded for token in banned)


def is_standard_cable_output(name: str) -> bool:
    folded = " ".join(name.lower().replace("(", " ").replace(")", " ").split())
    if not folded.startswith("cable output"):
        return False
    banned = ("cable a", "cable b", "cable c", "cable d", "hi-fi", "hifi", "asio", "16ch", "16 ch")
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
    return CableSelection(
        chosen.index, chosen.name, chosen.hostapi, channels, chosen.default_samplerate
    )


def device_rate(value: object) -> int:
    """A usable endpoint rate, or 0 when the device did not report one."""
    try:
        rate = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0
    if rate < _MIN_RATE or rate > _MAX_RATE:
        return 0
    return rate


def playback_rates(default_samplerate: int) -> list[int]:
    """Endpoint rate first, then 16000 Hz if it is different.

    The first rate is the one Windows already uses for that playback
    endpoint. 16000 Hz stays as a second try for a cable whose mix format
    really is 16 kHz, or whose driver will convert when asked.
    """
    rate = device_rate(default_samplerate)
    if rate == 0 or rate == SAMPLE_RATE:
        return [SAMPLE_RATE]
    return [rate, SAMPLE_RATE]


def pcm_peak(mono: bytes) -> int:
    """Largest absolute PCM16 sample. 0 means the buffer is digital silence."""
    usable = len(mono) - (len(mono) % 2)
    peak = 0
    for index in range(0, usable, 2):
        sample = int.from_bytes(mono[index : index + 2], "little", signed=True)
        magnitude = abs(sample)
        if magnitude > peak:
            peak = magnitude
    return peak


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


class Pcm16Resampler:
    """Streaming linear resampler. A constant input stays that constant."""

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self.src_rate = int(src_rate)
        self.dst_rate = int(dst_rate)
        self._prev = 0
        self._have = False
        # Next output position, in 1/dst_rate source-sample units.
        # Index 0 is _prev once a chunk has been seen; later indexes are the
        # samples of the chunk currently being fed.
        self._pos = 0

    def feed(self, mono: bytes) -> bytes:
        if len(mono) % 2:
            mono = mono[:-1]
        if self.src_rate == self.dst_rate or self.src_rate <= 0 or self.dst_rate <= 0:
            return mono
        count = len(mono) // 2
        if count == 0:
            return b""
        src = [int.from_bytes(mono[index : index + 2], "little", signed=True) for index in range(0, len(mono), 2)]
        if not self._have:
            self._prev = src[0]
            self._have = True
        den = self.dst_rate
        limit = count * den
        pos = self._pos
        step = self.src_rate
        out = bytearray()
        while pos < limit:
            index = pos // den
            frac = pos % den
            left = self._prev if index <= 0 else src[index - 1]
            right = src[index] if index < count else src[-1]
            sample = left + ((right - left) * frac) // den
            if sample > 32767:
                sample = 32767
            elif sample < -32768:
                sample = -32768
            out += int(sample).to_bytes(2, "little", signed=True)
            pos += step
        self._pos = pos - limit
        self._prev = src[-1]
        return bytes(out)


class PcmByteQueue:
    """Interleaved PCM waiting for the playback callback.

    push and pull may run on different threads. Overflow drops the oldest
    whole frames so the channel alignment never slips.
    """

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max(0, int(max_bytes))
        self._buf = bytearray()
        self._lock = threading.Lock()
        self.pulls = 0
        self.dropped = 0

    def push(self, data: bytes, frame_bytes: int) -> None:
        if not data:
            return
        frame = frame_bytes if frame_bytes > 0 else 1
        with self._lock:
            self._buf.extend(data)
            extra = len(self._buf) - self.max_bytes
            if extra <= 0:
                return
            aligned = (len(self._buf) // frame) * frame
            if self.max_bytes <= 0:
                drop = aligned
            else:
                drop = min(((extra + frame - 1) // frame) * frame, aligned)
            if drop:
                del self._buf[:drop]
                self.dropped += drop

    def pull(self, nbytes: int) -> bytes:
        """Exactly nbytes, zero-padded when the queue is short."""
        if nbytes <= 0:
            with self._lock:
                self.pulls += 1
            return b""
        with self._lock:
            self.pulls += 1
            got = bytes(self._buf[:nbytes])
            del self._buf[: len(got)]
        if len(got) < nbytes:
            got += bytes(nbytes - len(got))
        return got

    def snapshot(self) -> tuple[int, int, int]:
        """(callback pulls, dropped bytes, bytes still queued)."""
        with self._lock:
            return self.pulls, self.dropped, len(self._buf)


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
                default_samplerate=device_rate(device.get("default_samplerate", 0)),
            )
        )
    return rows


def _emit(log, line: str) -> None:
    if log is None:
        print(line)
        return
    try:
        log(line)
    except Exception:
        pass


class CableSink:
    """Plays 16 kHz PCM16 on one already-selected playback device.

    Writes queue PCM and return. A PortAudio callback drains the queue, so
    the caller never blocks inside the driver. WASAPI is opened in shared
    mode with autoconvert; exclusive mode and ASIO are not used.
    """

    def __init__(self, selection: CableSelection, log=None) -> None:
        if os.environ.get("SD_ENABLE_ASIO"):
            raise CableUnavailable(
                "检测到 SD_ENABLE_ASIO。本程序不加载 ASIO 版 PortAudio，也没有打开声卡。"
            )
        self._log = log
        self._stream = None
        self._queue: PcmByteQueue | None = None
        self._resampler: Pcm16Resampler | None = None
        self._generation = 0
        self._dead = False
        self._underruns = 0
        self._opened_at = 0.0
        self._last_log = 0.0
        self._pulls_seen = -1
        self._pulls_seen_at = 0.0
        self._frame_bytes = 2
        self.writes = 0
        self.peak = 0
        self.nonzero_writes = 0
        self.name = selection.name
        self.hostapi = selection.hostapi
        self.channels = selection.channels
        self.samplerate = SAMPLE_RATE
        rates = playback_rates(selection.default_samplerate)
        last: CableUnavailable | None = None
        for rate in rates:
            try:
                self._open_at(selection, rate)
            except CableUnavailable as exc:
                last = exc
                self._close_stream()
                if rate != rates[-1]:
                    _emit(self._log, f"cable retry hostapi={selection.hostapi} rate={rate}")
                continue
            _emit(
                self._log,
                f"cable open name={self.name} hostapi={self.hostapi} "
                f"channels={self.channels} rate={self.samplerate} source_hz={SAMPLE_RATE}",
            )
            return
        raise last if last is not None else CableUnavailable(OPEN_FAILED)

    def _open_at(self, selection: CableSelection, rate: int) -> None:
        import sounddevice as sd

        self._generation += 1
        generation = self._generation
        self._dead = False
        self._underruns = 0
        self.samplerate = rate
        self._frame_bytes = selection.channels * 2
        self._queue = PcmByteQueue(int(rate * self._frame_bytes * _QUEUE_SECONDS))
        self._resampler = None if rate == SAMPLE_RATE else Pcm16Resampler(SAMPLE_RATE, rate)
        extra = None
        if "wasapi" in selection.hostapi.lower():
            # Shared mode only. auto_convert makes Windows resample when the
            # opened rate is not the endpoint mix format, instead of accepting
            # the stream and then never pulling buffers.
            extra = sd.WasapiSettings(exclusive=False, auto_convert=True)

        def callback(outdata, _frames, _time, status, generation=generation) -> None:
            self._on_audio(generation, outdata, status)

        stream = None
        try:
            stream = sd.RawOutputStream(
                samplerate=rate,
                channels=selection.channels,
                dtype="int16",
                device=selection.index,
                blocksize=max(1, rate // 50),
                dither_off=True,
                latency=0.08,
                extra_settings=extra,
                callback=callback,
                finished_callback=lambda generation=generation: self._on_finished(generation),
            )
            stream.start()
        except CableUnavailable:
            raise
        except Exception as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            raise CableUnavailable(
                f"无法以 {rate} Hz 打开 CABLE Input（{type(exc).__name__}）。没有修改系统默认设备。"
            ) from None
        self._stream = stream
        self._opened_at = time.monotonic()
        # One period is 20 ms. If the callback has not run after a few of
        # those, this host API accepted the stream and then did not render.
        # Try another rate or API instead of reporting the cable as open.
        pulls = 0
        deadline = self._opened_at + 0.3
        while time.monotonic() < deadline and not self._dead:
            pulls, _dropped, _queued = self._queue.snapshot()
            if pulls:
                break
            time.sleep(0.01)
        if self._dead or pulls == 0:
            self._close_stream()
            raise CableUnavailable(
                f"无法以 {rate} Hz 打开 CABLE Input（播放回调没有运行）。没有修改系统默认设备。"
            )
        self._pulls_seen = pulls
        self._pulls_seen_at = self._opened_at

    def _on_audio(self, generation: int, outdata, status) -> None:
        try:
            if generation != self._generation or self._queue is None:
                outdata[:] = bytes(len(outdata))
                return
            payload = self._queue.pull(len(outdata))
            outdata[:] = payload
            if status and getattr(status, "output_underflow", True):
                self._underruns += 1
        except Exception:
            self._dead = True
            try:
                outdata[:] = bytes(len(outdata))
            except Exception:
                pass

    def _on_finished(self, generation: int) -> None:
        if generation == self._generation:
            self._dead = True

    def write(self, mono_pcm: bytes) -> None:
        peak = pcm_peak(mono_pcm)
        if self._resampler is None:
            pcm = mono_pcm[: len(mono_pcm) - (len(mono_pcm) % 2)]
        else:
            pcm = self._resampler.feed(mono_pcm)
        payload = expand_pcm(pcm, self.channels)
        queue = self._queue
        if payload and queue is not None:
            queue.push(payload, self._frame_bytes)
        self.writes += 1
        if peak > self.peak:
            self.peak = peak
        first_sound = peak > 0 and self.nonzero_writes == 0
        if peak > 0:
            self.nonzero_writes += 1
        self._maybe_log(force=self.writes == 1 or first_sound)
        if self._rendering_stopped(peak > 0):
            message = "CABLE Input 已打开但没有在播放。没有修改系统默认设备。"
            _emit(self._log, "cable error " + message)
            _emit(self._log, self.stats_line())
            raise CableUnavailable(message)

    def _rendering_stopped(self, audible: bool) -> bool:
        """True when the endpoint is not pulling queued audio.

        A callback that never starts, or that stops advancing while audible
        PCM keeps arriving, used to leave the tray on "transmitting" with
        both cable meters at zero. Fail the write instead of blocking.
        """
        if self._dead:
            return True
        queue = self._queue
        if queue is None or self._opened_at <= 0:
            return True
        pulls, _dropped, _queued = queue.snapshot()
        now = time.monotonic()
        if pulls == 0:
            return now - self._opened_at > _CALLBACK_GRACE_SECONDS
        if not audible:
            return False
        if pulls != self._pulls_seen:
            self._pulls_seen = pulls
            self._pulls_seen_at = now
            return False
        return now - self._pulls_seen_at > _CALLBACK_GRACE_SECONDS

    def _maybe_log(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_log < 1.0:
            return
        self._last_log = now
        _emit(self._log, self.stats_line())

    def stats_line(self) -> str:
        queue = self._queue
        pulls, dropped, queued = queue.snapshot() if queue is not None else (0, 0, 0)
        return (
            f"cable level writes={self.writes} peak={self.peak} "
            f"nonzero={self.nonzero_writes} callbacks={pulls} "
            f"underruns={self._underruns} dropped={dropped} queued={queued} "
            f"rate={self.samplerate} channels={self.channels}"
        )

    def _close_stream(self) -> None:
        # Bump the generation first so a callback still inside PortAudio does
        # not pull from a queue that belongs to the next attempt.
        self._generation += 1
        stream = self._stream
        self._stream = None
        self._queue = None
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def close(self) -> None:
        self._close_stream()


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


def open_cable_input(log=None) -> CableSink:
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
            device.default_samplerate,
        )
        try:
            return CableSink(selection, log=log)
        except CableUnavailable as exc:
            last_error = exc
            _emit(
                log,
                f"cable fallback hostapi={selection.hostapi} rate={selection.default_samplerate}",
            )
            continue
    if last_error is not None:
        raise last_error
    raise CableUnavailable(OPEN_FAILED)
