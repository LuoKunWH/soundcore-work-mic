"""Offline checks. They open no Bluetooth adapter and write no audio."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from soundcore_diag.cable import (
    MISSING_TEXT,
    CableMissing,
    OutputDevice,
    expand_pcm,
    is_standard_cable_input,
    select_cable_input,
)
from soundcore_diag.crypto_session import FILE_MAGIC, SessionCrypto, aes_ctr, derive_session_key
from soundcore_diag.harness import MemoryLink, rx_frame
from soundcore_diag.opus_pcm import OpusPcmDecoder, OpusUnavailable
from soundcore_diag.protocol import (
    ALLOWED_TX,
    ProtocolError,
    device_info_request,
    drain_packets,
    encode,
    handshake_request,
    parse_device_info,
    realtime_request,
    transfer_stop_request,
)
from soundcore_diag.session import run_diagnostic


class BytesDecoder:
    def __init__(self, pcm: bytes | None) -> None:
        self.pcm = pcm
        self.calls = 0

    def decode_frame(self, packet: bytes) -> bytes | None:
        self.calls += 1
        return self.pcm

    def close(self) -> None:
        return None


def _hkdf_reference(shared: bytes) -> bytes:
    import hashlib
    import hmac

    salt = bytes((1, 2, 3))
    info = bytes((1, 2, 3))
    prk = hmac.new(salt, shared, hashlib.sha256).digest()
    block = hmac.new(prk, info + bytes((1,)), hashlib.sha256).digest()
    return block[:32]


def _device_info_payload() -> bytes:
    payload = bytearray()
    payload.append(1)
    payload.append(5)
    payload.append(0)
    payload += b"04.92"
    payload += b"\x00" * 16
    payload += (1024).to_bytes(4, "little")
    payload += (512).to_bytes(4, "little")
    payload.append(0)
    payload += b"01.00"
    payload.append(9)
    payload += b"\x00" * 6
    payload += bytes((0, 0, 0, 0, 0, 1))
    payload += b"00.00"
    return bytes(payload)


class _Peer:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.session: bytes | None = None
        self.file_id = 100
        self.file_key = bytes(range(32))
        self.nonce = bytes(range(16))
        self.session_nonce = bytes(range(16, 32))
        self.transfers = 0

    def on_tx(self, frame: bytes) -> list[bytes]:
        cmd = (frame[5], frame[6])
        if self.mode == "silence":
            return []
        if self.mode == "disconnect":
            return []
        if cmd == (0x01, 0x01):
            if self.mode == "refuse_info":
                return [rx_frame(0x01, 0x01, b"\xff", status=1)]
            return [rx_frame(0x01, 0x01, _device_info_payload())]
        if cmd == (0x2E, 0x01):
            if self.mode == "refuse_handshake":
                return [rx_frame(0x2E, 0x01, b"\xff", status=1)]
            note = rx_frame(0x1A, 0x06, self.file_id.to_bytes(4, "little"))
            shake = self._handshake(frame[9:-1], mismatch=self.mode == "bad_shared")
            return [shake, note]
        if cmd == (0x1A, 0x07):
            if self.mode == "refuse_realtime":
                return [rx_frame(0x1A, 0x07, b"\xff", status=1)]
            file_id = int.from_bytes(frame[13:17], "little")
            head_id = file_id + 1 if self.mode == "file_mismatch" else file_id
            frames = [self._head(head_id)]
            if self.mode == "bad_opus":
                frames.append(self._slice(0, bytes(range(160))))
            elif self.mode == "gap":
                frames.append(self._slice(0, b"\x11" * 160))
                frames.append(self._slice(2, b"\x22" * 160))
            elif self.mode == "good":
                frames.append(self._slice(0, b"\x33" * 160))
            elif self.mode == "change_file":
                frames.append(rx_frame(0x1A, 0x06, (file_id + 9).to_bytes(4, "little")))
            elif self.mode == "pause_resume":
                # The first transfer is paused on the device after one slice.
                # The resumed one starts again from slice 0.
                self.transfers += 1
                frames.append(self._slice(0, b"\x33" * 160))
                if self.transfers == 1:
                    frames.append(rx_frame(0x1A, 0x0A))
                else:
                    frames.append(self._slice(1, b"\x34" * 160))
            return frames
        if cmd == (0x1A, 0x11) and self.mode == "pause_resume" and self.transfers == 1:
            return [rx_frame(0x1A, 0x06, self.file_id.to_bytes(4, "little"))]
        return []

    def _handshake(self, app_public: bytes, mismatch: bool) -> bytes:
        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), app_public)
        shared = self.private.exchange(ec.ECDH(), peer)
        self.session = derive_session_key(shared)
        public = self.private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        sent = b"\x00" * 32 if mismatch else shared
        return rx_frame(0x2E, 0x01, public + sent)

    def _head(self, file_id: int) -> bytes:
        assert self.session is not None
        plain = FILE_MAGIC + self.file_key
        encrypted = aes_ctr(self.session, self.session_nonce, plain)
        assert encrypted is not None
        payload = bytearray()
        payload += file_id.to_bytes(4, "little")
        payload += (160).to_bytes(4, "little")
        payload += self.nonce
        payload += encrypted
        payload += self.session_nonce
        payload.append(0)
        return rx_frame(0x1A, 0x07, bytes(payload))

    def _slice(self, sequence: int, plain: bytes) -> bytes:
        assert self.session is not None
        counter = (sequence * 10).to_bytes(4, "big")
        iv = self.nonce[:12] + counter
        encrypted = aes_ctr(self.file_key, iv, plain)
        assert encrypted is not None
        payload = sequence.to_bytes(4, "little") + b"\x00" + encrypted + b"\x00"
        return rx_frame(0x1A, 0x08, payload)


async def _drive(link: MemoryLink, peer: _Peer) -> None:
    seen = 0
    while not link.closed:
        if len(link.writes) == seen:
            await asyncio.sleep(0.005)
            continue
        frame = link.writes[seen]
        seen += 1
        if peer.mode == "disconnect" and seen == 1:
            await link.disconnect()
            return
        for reply in peer.on_tx(frame):
            if peer.mode == "split" and reply[5] == 0x2E:
                link.push(reply[:12])
                link.push(reply[12:])
            else:
                link.push(reply)
        if peer.mode == "good" and frame[5] == 0x1A and frame[6] == 0x07:
            await asyncio.sleep(0.05)


class _CountingSink:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.writes = 0
        self.nbytes = 0

    def write(self, pcm: bytes) -> None:
        self.writes += 1
        self.nbytes += len(pcm)
        if self.fail:
            raise RuntimeError("missing cable")

    def close(self) -> None:
        self.nbytes = 0


async def exercise(mode: str, decoder, seconds: float = 0.6, sink=None, stop=None, on_rearm=None):
    link = MemoryLink()
    peer = _Peer(mode)
    driver = asyncio.create_task(_drive(link, peer))
    result = await run_diagnostic(
        link,
        decoder,
        deadline=time.monotonic() + seconds,
        pcm_timeout=0.35,
        command_timeout=0.35,
        sink=sink,
        stop=stop,
        on_rearm=on_rearm,
    )
    await asyncio.wait_for(driver, 1)
    return link, result


def _check_allowlist() -> None:
    forbidden = [
        (0x01, 0xA6, b""),
        (0x01, 0xB8, b""),
        (0x18, 0x82, b"\x01"),
        (0x18, 0x82, b"\x02"),
        (0x1A, 0x0E, b"\x00\x00"),
        (0x1B, 0x0E, b"\x00\x00"),
        (0x1A, 0x10, b"\x01\x00\x00\x00"),
        (0x1A, 0x0F, b"\x00"),
        (0x1A, 0x05, b"\x00"),
        (0x1A, 0x02, b""),
        (0x0B, 0x87, b"\x01"),
        (0x0B, 0x87, b"\x00"),
        (0x10, 0xA2, b"\x01"),
    ]
    for cmd_type, cmd_id, payload in forbidden:
        try:
            encode(cmd_type, cmd_id, payload)
        except ProtocolError:
            continue
        raise AssertionError(f"allowed forbidden command {cmd_type:02x}/{cmd_id:02x}")
    try:
        encode(0x1A, 0x07, b"\x01\x00\x00\x00\x02\x00\x00\x00\x01")
        raise AssertionError("nonzero offset was accepted")
    except ProtocolError:
        pass
    try:
        encode(0x1A, 0x07, b"\x00\x00\x00\x00\x02\x00\x00\x00\x00")
        raise AssertionError("offline flag was accepted")
    except ProtocolError:
        pass
    info = device_info_request()
    assert info[5:7] == b"\x01\x01" and info[9:-1] == b""
    stop = transfer_stop_request()
    assert stop[5:7] == b"\x1a\x11" and stop[9:-1] == b"\x00"
    live = realtime_request(7)
    assert live[9:13] == b"\x00\x00\x00\x00" and live[13:17] == b"\x07\x00\x00\x00" and live[17] == 1
    assert ALLOWED_TX == {(0x01, 0x01), (0x2E, 0x01), (0x1A, 0x07), (0x1A, 0x11)}
    public = bytes([0x04]) + bytes(64)
    frame = handshake_request(public)
    assert frame[5:7] == b"\x2e\x01" and frame[9:-1] == public


def _check_parse() -> None:
    info = parse_device_info(_device_info_payload())
    assert info is not None
    assert info.firmware_field == "04.92"
    assert info.recording_byte == 1
    assert info.mic_battery_percent == 60
    assert info.case_battery_percent == 100
    assert not hasattr(info, "serial_number")
    raw = rx_frame(0x1A, 0x06, (42).to_bytes(4, "little"))
    buf = bytearray(b"\x00\x01" + raw[:5])
    assert drain_packets(buf) == []
    buf.extend(raw[5:])
    packets = drain_packets(buf)
    assert len(packets) == 1 and packets[0].payload == (42).to_bytes(4, "little")
    refused = rx_frame(0x2E, 0x01, b"\xff", status=1)
    packet = drain_packets(bytearray(refused))[0]
    assert packet.rejected and not packet.success


def _check_crypto() -> None:
    app = SessionCrypto()
    device = ec.generate_private_key(ec.SECP256R1())
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), app.public_uncompressed())
    shared = device.exchange(ec.ECDH(), peer)
    assert derive_session_key(shared) == _hkdf_reference(shared)
    device_public = device.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    assert app.complete(device_public, shared)
    assert not SessionCrypto().complete(device_public, b"\x01" * 32)
    session = derive_session_key(shared)
    nonce = bytes(range(16))
    session_nonce = bytes(range(16, 32))
    file_key = bytes(reversed(range(32)))
    encrypted = aes_ctr(session, session_nonce, FILE_MAGIC + file_key)
    assert encrypted is not None
    assert app.install_file_key(encrypted, session_nonce, nonce)
    iv = nonce[:12] + (10).to_bytes(4, "big")
    blob = aes_ctr(file_key, iv, b"\x44" * 160)
    assert blob is not None
    assert app.decrypt_chunk(1, blob) == b"\x44" * 160
    app.wipe()


def _check_cable() -> None:
    assert "https://vb-audio.com/Cable/" in MISSING_TEXT
    assert "VBCABLE_Driver_Pack46.zip" in MISSING_TEXT
    assert "A+B" in MISSING_TEXT
    assert "CABLE Output" in MISSING_TEXT
    assert "CABLE Input" in MISSING_TEXT
    assert not is_standard_cable_input("CABLE Output (VB-Audio Virtual Cable)")
    assert not is_standard_cable_input("CABLE-A Input")
    assert not is_standard_cable_input("CABLE Input (VB-Audio Cable A)")
    assert not is_standard_cable_input("Hi-Fi Cable Input")
    assert is_standard_cable_input("CABLE Input")
    assert is_standard_cable_input("CABLE Input (VB-Audio Virtual Cable)")
    try:
        select_cable_input([])
    except CableMissing as exc:
        assert str(exc) == MISSING_TEXT
    else:
        raise AssertionError("missing cable was accepted")
    chosen = select_cable_input(
        [
            OutputDevice(1, "CABLE Output (VB-Audio Virtual Cable)", "Windows WASAPI", 2),
            OutputDevice(2, "CABLE Input (VB-Audio Virtual Cable)", "MME", 2),
            OutputDevice(3, "CABLE Input (VB-Audio Virtual Cable)", "Windows WASAPI", 2),
            OutputDevice(4, "CABLE Input (VB-Audio Cable A)", "Windows WASAPI", 2),
            OutputDevice(5, "CABLE Input (VB-Audio Virtual Cable)", "ASIO", 2),
        ]
    )
    assert chosen.index == 3 and chosen.channels == 2
    mono = select_cable_input([OutputDevice(7, "CABLE Input", "MME", 1)])
    assert mono.index == 7 and mono.channels == 1
    try:
        select_cable_input(
            [
                OutputDevice(1, "CABLE Input (VB-Audio Virtual Cable)", "Windows WASAPI", 2),
                OutputDevice(2, "CABLE Input (VB-Audio Virtual Cable)", "Windows WASAPI", 2),
            ]
        )
    except CableMissing:
        pass
    else:
        raise AssertionError("ambiguous cable was accepted")
    assert expand_pcm(b"\x01\x00\x02\x00", 2) == b"\x01\x00\x01\x00\x02\x00\x02\x00"
    assert expand_pcm(b"\x01\x00", 1) == b"\x01\x00"


def _snapshot() -> set[str]:
    return set(os.listdir(Path.cwd()))


def run_self_test() -> int:
    if "bleak" in sys.modules or "soundcore_diag.live" in sys.modules:
        print("自检开始前已经加载了蓝牙模块。")
        return 1
    before = _snapshot()
    try:
        _check_allowlist()
        print("协议允许列表: 通过")
        _check_parse()
        print("报文解析: 通过")
        _check_crypto()
        print("会话加密往返: 通过")
        _check_cable()
        print("虚拟声卡选择: 通过")
        silence_pcm = b"\x00\x00" * 320

        async def mocks() -> None:
            link, result = await exercise("refuse_info", BytesDecoder(silence_pcm), 0.5)
            assert result.stop_reason == "refused"
            assert link.disconnects == 1
            assert all(item != (0x1A, 0x07) for item in result.commands)
            assert result.transfer_stop_sent is False

            link, result = await exercise("refuse_handshake", BytesDecoder(silence_pcm), 0.5)
            assert result.stop_reason == "refused"
            assert (0x1A, 0x07) not in result.commands

            link, result = await exercise("bad_shared", BytesDecoder(silence_pcm), 0.5)
            assert result.stop_reason == "crypto_failure"
            assert (0x1A, 0x07) not in result.commands

            link, result = await exercise("silence", BytesDecoder(silence_pcm), 0.25)
            assert result.stop_reason == "timeout"
            assert link.disconnects == 1
            assert (0x1A, 0x07) not in result.commands

            link, result = await exercise("disconnect", BytesDecoder(silence_pcm), 0.5)
            assert result.stop_reason == "disconnected"
            assert link.disconnects == 1
            assert (0x1A, 0x07) not in result.commands

            link, result = await exercise("refuse_realtime", BytesDecoder(silence_pcm), 0.8)
            assert result.stop_reason == "refused"
            assert result.transfer_stop_sent is True
            assert (0x18, 0x82) not in result.commands

            link, result = await exercise("bad_opus", BytesDecoder(None), 0.8)
            assert result.stop_reason == "decode_failure"
            assert result.pcm_frames == 0
            assert result.transfer_stop_sent is True
            assert (0x18, 0x82) not in result.commands

            link, result = await exercise("good", BytesDecoder(silence_pcm), 0.45)
            assert result.stop_reason == "duration_cap"
            assert result.pcm_frames >= 1
            assert result.duration_ms == 20
            assert result.transfer_stop_sent is True
            assert result.firmware_field == "04.92"
            assert result.command_names[-1] == "transfer_stop"
            assert (0x18, 0x82) not in result.commands
            assert link.disconnects == 1

            _link, result = await exercise("file_mismatch", BytesDecoder(silence_pcm), 0.8)
            assert result.stop_reason == "file_mismatch"
            assert result.pcm_frames == 0

            _link, result = await exercise("gap", BytesDecoder(silence_pcm), 0.8)
            assert result.stop_reason == "protocol_error"

            _link, result = await exercise("change_file", BytesDecoder(silence_pcm), 0.8)
            assert result.stop_reason == "active_file_changed"

            _link, result = await exercise("pause_resume", BytesDecoder(silence_pcm), 0.6)
            assert result.stop_reason == "transfer_finished"
            assert result.command_names.count("realtime_active") == 1

            rearms = []
            link, result = await exercise(
                "pause_resume", BytesDecoder(silence_pcm), 0.6, on_rearm=lambda: rearms.append(1)
            )
            assert result.stop_reason == "duration_cap"
            assert rearms == [1]
            assert result.pcm_frames == 2
            assert result.command_names[2:] == [
                "realtime_active", "transfer_stop", "realtime_active", "transfer_stop"
            ]
            assert (0x18, 0x82) not in result.commands
            assert link.disconnects == 1

            sink = _CountingSink()
            _link, result = await exercise("good", BytesDecoder(silence_pcm), 0.45, sink=sink)
            assert result.stop_reason == "duration_cap"
            assert result.cable_writes == sink.writes and sink.writes >= 1
            sink.close()

            failing = _CountingSink(fail=True)
            _link, result = await exercise("good", BytesDecoder(silence_pcm), 0.8, sink=failing)
            assert result.stop_reason == "cable_error"
            assert result.transfer_stop_sent is True
            assert (0x18, 0x82) not in result.commands
            failing.close()

            _link, result = await exercise(
                "silence",
                BytesDecoder(silence_pcm),
                0.4,
                stop=lambda: True,
            )
            assert result.stop_reason == "stopped"
            assert (0x1A, 0x07) not in result.commands
            assert _link.disconnects == 1

        asyncio.run(mocks())
        print("拒绝、超时、断开和停止条件: 通过")
        native = "未执行"
        try:
            decoder = OpusPcmDecoder()
            try:
                native = f"{decoder.info.origin} {decoder.info.version}"
            finally:
                decoder.close()
        except OpusUnavailable:
            native = "当前进程没有可用的 Opus 解码器"
        print(f"原生解码器探测: {native}")
    except Exception as exc:
        print(f"自检失败: {type(exc).__name__}")
        return 1
    finally:
        pass
    if _snapshot() != before:
        print("自检期间目录内容发生变化。")
        return 1
    if "bleak" in sys.modules or "soundcore_diag.live" in sys.modules:
        print("自检加载了蓝牙模块。")
        return 1
    print("自检通过。没有扫描或连接蓝牙，也没有保存音频。")
    return 0
