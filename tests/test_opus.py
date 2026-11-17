"""Native Opus round trip when a library is already available."""

from __future__ import annotations

import ctypes
import unittest

from soundcore_diag.opus_pcm import OpusPcmDecoder, OpusUnavailable, load_opus, trim_opus_packet


class OpusTests(unittest.TestCase):
    def test_trim_keeps_a_nonzero_tail(self) -> None:
        self.assertEqual(trim_opus_packet(b"\x01\x00\x02\x00\x00"), b"\x01\x00\x02")

    def test_silence_roundtrip_at_16k_mono(self) -> None:
        try:
            lib, _info = load_opus()
        except OpusUnavailable as exc:
            self.skipTest(str(exc))
        lib.opus_encoder_create.argtypes = [
            ctypes.c_int32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.opus_encoder_create.restype = ctypes.c_void_p
        lib.opus_encode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int32,
        ]
        lib.opus_encode.restype = ctypes.c_int32
        lib.opus_encoder_destroy.argtypes = [ctypes.c_void_p]
        lib.opus_encoder_destroy.restype = None
        error = ctypes.c_int()
        encoder = lib.opus_encoder_create(16000, 1, 2049, ctypes.byref(error))
        self.assertTrue(encoder)
        self.assertEqual(error.value, 0)
        pcm = (ctypes.c_int16 * 320)()
        encoded = (ctypes.c_ubyte * 400)()
        size = lib.opus_encode(encoder, pcm, 320, encoded, 400)
        self.assertGreater(size, 0)
        packet = bytes(encoded[:size])
        decoder = OpusPcmDecoder()
        try:
            plain = decoder.decode_frame(packet)
            self.assertIsNotNone(plain)
            assert plain is not None
            self.assertEqual(len(plain), 640)
            if packet[-1] != 0:
                padded = packet + b"\x00" * (160 - len(packet))
                again = decoder.decode_frame(padded)
                self.assertIsNotNone(again)
                assert again is not None
                self.assertEqual(len(again), 640)
        finally:
            decoder.close()
            lib.opus_encoder_destroy(encoder)


if __name__ == "__main__":
    unittest.main()
