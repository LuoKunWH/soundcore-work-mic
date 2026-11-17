"""Report installed modules and the Opus decoder. Does not import bleak."""

from __future__ import annotations

import importlib.util
import platform
import sys

from soundcore_diag.opus_pcm import OpusPcmDecoder, OpusUnavailable


def run_check_env() -> int:
    print(f"python: {sys.version.split()[0]} {platform.architecture()[0]}")
    print(f"platform: {platform.system()} {platform.release()} {platform.machine()}")
    bleak_present = importlib.util.find_spec("bleak") is not None
    print(f"bleak_module: {'present' if bleak_present else 'absent'}")
    sounddevice_present = importlib.util.find_spec("sounddevice") is not None
    print(f"sounddevice_module: {'present' if sounddevice_present else 'absent'}")
    crypto_ok = False
    try:
        import cryptography

        crypto_ok = True
        print(f"cryptography: {cryptography.__version__}")
    except Exception:
        print("cryptography: import failed")
    opus_ok = False
    decoder = None
    try:
        decoder = OpusPcmDecoder()
        info = decoder.info
        opus_ok = True
        print(f"opus_origin: {info.origin}")
        print(f"opus_path: {info.path}")
        print(f"opus_version: {info.version}")
        print(f"opus_sha256: {info.sha256 or 'not-applicable'}")
        print("opus_decoder: create-ok")
    except OpusUnavailable:
        print("opus_decoder: unavailable")
    finally:
        if decoder is not None:
            decoder.close()
    imported = "yes" if "bleak" in sys.modules else "no"
    print(f"bleak_imported: {imported}")
    sounddevice_imported = "yes" if "sounddevice" in sys.modules else "no"
    print(f"sounddevice_imported: {sounddevice_imported}")
    if imported == "yes" or sounddevice_imported == "yes":
        print("check-env imported bleak or sounddevice")
        return 2
    if bleak_present and sounddevice_present and crypto_ok and opus_ok:
        print("check-env: ok")
        return 0
    print("check-env: incomplete")
    return 2
