"""Decode one Opus packet to 16 kHz mono PCM16.

Windows loads only opus.dll shipped inside the pinned PyOgg wheel. Other
platforms may load a system libopus for the offline decode check. This module
does not play audio and does not write it.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 16000
CHANNELS = 1
MAX_SAMPLES = 1920
OPUS_DLL_SHA256 = "5fa25b62f72f880acf420120d8ca32d31997620cadaab26ae798d13355012d1b"


class OpusUnavailable(Exception):
    pass


@dataclass(frozen=True)
class OpusLibrary:
    origin: str
    path: str
    version: str
    sha256: str | None


def _bind(lib: ctypes.CDLL) -> None:
    lib.opus_get_version_string.argtypes = []
    lib.opus_get_version_string.restype = ctypes.c_char_p
    lib.opus_decoder_create.argtypes = [
        ctypes.c_int32,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.opus_decoder_create.restype = ctypes.c_void_p
    lib.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
    lib.opus_decoder_destroy.restype = None
    lib.opus_decode.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_int32,
        ctypes.POINTER(ctypes.c_int16),
        ctypes.c_int,
        ctypes.c_int,
    ]
    lib.opus_decode.restype = ctypes.c_int


def _version_of(lib: ctypes.CDLL) -> str:
    raw = lib.opus_get_version_string()
    if not raw:
        return ""
    return raw.decode("ascii", "replace")


def load_opus() -> tuple[ctypes.CDLL, OpusLibrary]:
    if sys.platform == "win32":
        spec = importlib.util.find_spec("pyogg")
        locations = list(spec.submodule_search_locations or []) if spec else []
        if not locations:
            raise OpusUnavailable("PyOgg wheel is not installed")
        dll = Path(locations[0]) / "opus.dll"
        if not dll.is_file():
            raise OpusUnavailable("opus.dll is missing from the PyOgg wheel")
        digest = hashlib.sha256(dll.read_bytes()).hexdigest()
        if digest != OPUS_DLL_SHA256:
            raise OpusUnavailable("opus.dll hash does not match the pinned wheel")
        lib = ctypes.CDLL(str(dll))
        _bind(lib)
        return lib, OpusLibrary("pyogg-wheel", str(dll), _version_of(lib), digest)

    found = ctypes.util.find_library("opus")
    if not found:
        raise OpusUnavailable("system libopus was not found")
    lib = ctypes.CDLL(found)
    _bind(lib)
    return lib, OpusLibrary("system", found, _version_of(lib), None)


def trim_opus_packet(packet: bytes) -> bytes:
    end = len(packet)
    while end > 1 and packet[end - 1] == 0:
        end -= 1
    return packet[:end]


class OpusPcmDecoder:
    def __init__(self) -> None:
        lib, info = load_opus()
        self.info = info
        self._lib = lib
        error = ctypes.c_int()
        handle = lib.opus_decoder_create(SAMPLE_RATE, CHANNELS, ctypes.byref(error))
        if not handle or error.value != 0:
            raise OpusUnavailable("opus_decoder_create failed")
        self._handle = handle
        self._pcm = (ctypes.c_int16 * MAX_SAMPLES)()

    def decode_frame(self, packet: bytes) -> bytes | None:
        trimmed = trim_opus_packet(packet)
        if not trimmed:
            return None
        buffer = (ctypes.c_ubyte * len(trimmed)).from_buffer_copy(trimmed)
        count = self._lib.opus_decode(
            self._handle,
            buffer,
            len(trimmed),
            self._pcm,
            MAX_SAMPLES,
            0,
        )
        if count <= 0:
            return None
        return ctypes.string_at(self._pcm, count * 2)

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle:
            self._lib.opus_decoder_destroy(handle)
            self._handle = None
