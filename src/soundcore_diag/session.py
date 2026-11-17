"""One diagnostic session over an already-open notification stream.

Allowed transmit order:
  01/01, then 2E/01, then at most one 1A/07 for the file id from 1A/06,
  then one 1A/11 if that 1A/07 was sent.

With rearm, a transfer the device ends with 1A/0A (the user paused or
stopped the recording on the device) is closed with its 1A/11 and the
session waits on the same connection for the next 1A/06. Each 1A/06 allows
one more 1A/07. Slices of the same file that were already played are not
played again.

1A/11 stops the transfer. This session never builds a recording-control frame.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass, field

from soundcore_diag.crypto_session import SessionCrypto
from soundcore_diag.harness import LinkClosed
from soundcore_diag.protocol import (
    DeviceInfo,
    Packet,
    ProtocolError,
    assert_tx_frame,
    device_info_request,
    drain_packets,
    handshake_request,
    parse_active_file_id,
    parse_device_info,
    parse_file_head,
    parse_handshake,
    parse_slices,
    realtime_request,
    transfer_stop_request,
)

COMMAND_NAMES = {
    (0x01, 0x01): "device_info",
    (0x2E, 0x01): "handshake",
    (0x1A, 0x07): "realtime_active",
    (0x1A, 0x11): "transfer_stop",
}


@dataclass
class SessionResult:
    stop_reason: str
    firmware_field: str = ""
    recording_byte: int | None = None
    mic_battery_percent: int | None = None
    case_battery_percent: int | None = None
    notify_count: int = 0
    slice_count: int = 0
    decrypted_frames: int = 0
    pcm_frames: int = 0
    pcm_samples: int = 0
    duration_ms: int = 0
    peak_abs: int = 0
    rms: float = 0.0
    commands: list[tuple[int, int]] = field(default_factory=list)
    transfer_stop_sent: bool = False
    cable_writes: int | None = None

    @property
    def command_names(self) -> list[str]:
        return [COMMAND_NAMES.get(item, "blocked") for item in self.commands]


class _UserStop(Exception):
    pass


class _CableWriteFailed(Exception):
    pass


class _Runner:
    def __init__(
        self,
        link,
        decoder,
        deadline: float | None,
        pcm_timeout: float | None,
        command_timeout: float,
        sink=None,
        stop=None,
        on_rearm=None,
    ):
        self.link = link
        self.decoder = decoder
        self.deadline = deadline
        self.pcm_timeout = pcm_timeout
        self.command_timeout = command_timeout
        self.sink = sink
        self._stop = stop
        self._on_rearm = on_rearm
        self._peer_finished = False
        self._played: dict[int, int] = {}
        self.buffer = bytearray()
        self.pending: deque[Packet] = deque()
        self.crypto = SessionCrypto()
        self.result = SessionResult(stop_reason="protocol_error")
        self.active_file_id: int | None = None
        self.transfer_started = False
        self._samples = 0
        self._sum_sq = 0
        self._peak = 0
        self._pcm_frames = 0
        if sink is not None:
            self.result.cable_writes = 0

    def _user_stop(self) -> bool:
        return self._stop is not None and bool(self._stop())

    def _timed_out(self) -> bool:
        return self.deadline is not None and time.monotonic() >= self.deadline

    def _wait_slice(self, cap: float) -> float:
        if self.deadline is None:
            return cap
        remain = self.deadline - time.monotonic()
        if remain <= 0:
            return 0.0
        return min(cap, remain)

    def _command_window(self) -> float:
        return self._wait_slice(self.command_timeout)

    def _overflow(self) -> bool:
        return bool(getattr(self.link, "overflow", False))

    async def _write(self, frame: bytes) -> None:
        assert_tx_frame(frame)
        await self.link.write(frame)
        self.result.commands.append((frame[5], frame[6]))

    async def _next_packet(self, timeout: float) -> Packet | None:
        if self._user_stop():
            raise _UserStop()
        if self.pending:
            return self.pending.popleft()
        end = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < end:
            if self._user_stop():
                raise _UserStop()
            if self.pending:
                return self.pending.popleft()
            remain = end - time.monotonic()
            try:
                chunk = await asyncio.wait_for(self.link.queue.get(), remain)
            except TimeoutError:
                return None
            if chunk is None:
                raise LinkClosed()
            self.result.notify_count += 1
            self.buffer.extend(chunk)
            self.pending.extend(drain_packets(self.buffer))
            if len(self.buffer) > 65536:
                raise ProtocolError("receive buffer limit")
        return self.pending.popleft() if self.pending else None

    async def _wait_for(self, cmd_type: int, cmd_id: int, timeout: float) -> Packet | None:
        end = time.monotonic() + max(0.0, timeout)
        while True:
            remain = end - time.monotonic()
            if remain <= 0:
                return None
            packet = await self._next_packet(remain)
            if packet is None:
                return None
            if packet.cmd_type == cmd_type and packet.cmd_id == cmd_id:
                return packet
            self._note_early(packet)

    def _note_early(self, packet: Packet) -> None:
        if packet.cmd_type == 0x1A and packet.cmd_id == 0x06 and not self.transfer_started:
            file_id = parse_active_file_id(packet.payload)
            if file_id is not None:
                self.active_file_id = file_id

    def _consume_pcm(self, pcm: bytes) -> None:
        usable = len(pcm) - (len(pcm) % 2)
        if usable <= 0:
            raise ProtocolError("empty pcm")
        for index in range(0, usable, 2):
            sample = int.from_bytes(pcm[index : index + 2], "little", signed=True)
            self._samples += 1
            self._sum_sq += sample * sample
            magnitude = abs(sample)
            if magnitude > self._peak:
                self._peak = magnitude
        self._pcm_frames += 1
        if self.sink is None:
            return
        try:
            self.sink.write(pcm)
        except Exception as exc:
            raise _CableWriteFailed() from exc
        self.result.cable_writes = (self.result.cable_writes or 0) + 1

    def _fill_levels(self) -> None:
        self.result.pcm_frames = self._pcm_frames
        self.result.pcm_samples = self._samples
        self.result.peak_abs = self._peak
        self.result.duration_ms = (self._samples * 1000) // 16000
        if self._samples:
            self.result.rms = math.sqrt(self._sum_sq / self._samples)

    async def _stream(self, file_id: int) -> None:
        if self.pcm_timeout is None:
            pcm_deadline = self.deadline
        else:
            pcm_deadline = time.monotonic() + self.pcm_timeout
            if self.deadline is not None:
                pcm_deadline = min(pcm_deadline, self.deadline)
        expected: int | None = None
        head_ready = False
        played_up_to = self._played.get(file_id, 0)
        while not self._timed_out():
            if self._user_stop():
                self.result.stop_reason = "stopped"
                return
            if self._overflow():
                self.result.stop_reason = "notify_overflow"
                return
            if (
                self._pcm_frames == 0
                and pcm_deadline is not None
                and time.monotonic() >= pcm_deadline
            ):
                self.result.stop_reason = "no_valid_pcm"
                return
            packet = await self._next_packet(self._wait_slice(0.2))
            if packet is None:
                continue
            if packet.cmd_type == 0x1A and packet.cmd_id == 0x06:
                new_id = parse_active_file_id(packet.payload)
                if new_id is not None and new_id != file_id:
                    self.result.stop_reason = "active_file_changed"
                    return
                continue
            if packet.cmd_type == 0x1A and packet.cmd_id == 0x07:
                if packet.rejected or not packet.success:
                    self.result.stop_reason = "refused"
                    return
                head = parse_file_head(packet.payload)
                if head is None:
                    self.result.stop_reason = "protocol_error"
                    return
                if head.file_id != file_id:
                    self.result.stop_reason = "file_mismatch"
                    return
                if head.error_code != 0:
                    self.result.stop_reason = "refused"
                    return
                if not self.crypto.install_file_key(
                    head.encrypted_file_key,
                    head.session_nonce,
                    head.nonce,
                ):
                    self.result.stop_reason = "crypto_failure"
                    return
                head_ready = True
                continue
            if packet.cmd_type == 0x1A and packet.cmd_id in (0x08, 0x12):
                if not head_ready:
                    self.result.stop_reason = "protocol_error"
                    return
                slices = parse_slices(packet.raw)
                if not slices:
                    self.result.stop_reason = "protocol_error"
                    return
                for sequence, blob in slices:
                    self.result.slice_count += 1
                    if expected is None:
                        expected = sequence
                    elif sequence != expected:
                        self.result.stop_reason = "protocol_error"
                        return
                    expected = (sequence + 1) & 0xFFFFFFFF
                    if sequence < played_up_to:
                        continue
                    plain = self.crypto.decrypt_chunk(sequence, blob)
                    if plain is None:
                        self.result.stop_reason = "crypto_failure"
                        return
                    self.result.decrypted_frames += 1
                    pcm = self.decoder.decode_frame(plain)
                    if not pcm:
                        self.result.stop_reason = "decode_failure"
                        return
                    self._consume_pcm(pcm)
                    played_up_to = sequence + 1
                    self._played[file_id] = played_up_to
                continue
            if packet.cmd_type == 0x1A and packet.cmd_id == 0x0A:
                self._peer_finished = True
                self.result.stop_reason = "transfer_finished" if self._pcm_frames else "no_valid_pcm"
                return
        if self._user_stop():
            self.result.stop_reason = "stopped"
            return
        self.result.stop_reason = "duration_cap" if self._pcm_frames else "no_valid_pcm"

    async def run(self) -> SessionResult:
        try:
            if self._overflow() or self._timed_out():
                self.result.stop_reason = "timeout"
                return self.result
            await self._write(device_info_request())
            info_packet = await self._wait_for(0x01, 0x01, self._command_window())
            if info_packet is None:
                self.result.stop_reason = "timeout"
                return self.result
            if info_packet.rejected or not info_packet.success:
                self.result.stop_reason = "refused"
                return self.result
            info = parse_device_info(info_packet.payload)
            if info is None:
                self.result.stop_reason = "protocol_error"
                return self.result
            self._remember_info(info)
            if self._timed_out():
                self.result.stop_reason = "timeout"
                return self.result

            await self._write(handshake_request(self.crypto.public_uncompressed()))
            shake = await self._wait_for(0x2E, 0x01, self._command_window())
            if shake is None:
                self.result.stop_reason = "timeout"
                return self.result
            if shake.rejected or not shake.success:
                self.result.stop_reason = "refused"
                return self.result
            material = parse_handshake(shake.payload)
            if material is None or not self.crypto.complete(material[0], material[1]):
                self.result.stop_reason = "crypto_failure"
                return self.result

            while True:
                file_id = await self._wait_file()
                if file_id is None:
                    if self._user_stop():
                        self.result.stop_reason = "stopped"
                    elif self._timed_out():
                        self.result.stop_reason = "timeout"
                    else:
                        self.result.stop_reason = "no_active_file"
                    return self.result
                if self._timed_out():
                    self.result.stop_reason = "timeout"
                    return self.result
                await self._write(realtime_request(file_id))
                self.transfer_started = True
                await self._stream(file_id)
                if self._on_rearm is None or not self._peer_finished:
                    return self.result
                await self._stop_transfer()
                self._peer_finished = False
                self.active_file_id = None
                self._on_rearm()
        except _UserStop:
            self.result.stop_reason = "stopped"
            return self.result
        except _CableWriteFailed:
            self.result.stop_reason = "cable_error"
            return self.result
        except LinkClosed:
            self.result.stop_reason = "disconnected"
            return self.result
        except ProtocolError:
            self.result.stop_reason = "protocol_error"
            return self.result
        except Exception:
            self.result.stop_reason = "link_error"
            return self.result
        finally:
            await self._cleanup()

    async def _wait_file(self) -> int | None:
        if self.active_file_id:
            return self.active_file_id
        while not self._timed_out():
            if self._user_stop():
                return None
            if self._overflow():
                return None
            packet = await self._next_packet(self._wait_slice(0.2))
            if packet is None:
                continue
            if packet.cmd_type == 0x1A and packet.cmd_id == 0x06:
                file_id = parse_active_file_id(packet.payload)
                if file_id is not None:
                    return file_id
        return None

    def _remember_info(self, info: DeviceInfo) -> None:
        self.result.firmware_field = info.firmware_field
        self.result.recording_byte = info.recording_byte
        self.result.mic_battery_percent = info.mic_battery_percent
        self.result.case_battery_percent = info.case_battery_percent

    async def _stop_transfer(self) -> None:
        if self.transfer_started and not self.link.closed:
            self.transfer_started = False
            await self._write(transfer_stop_request())
            self.result.transfer_stop_sent = True

    async def _cleanup(self) -> None:
        self._fill_levels()
        try:
            await self._stop_transfer()
        except Exception:
            pass
        try:
            await self.link.disconnect()
        except Exception:
            pass
        self.crypto.wipe()


async def run_diagnostic(
    link,
    decoder,
    *,
    deadline: float | None,
    pcm_timeout: float | None = 8.0,
    command_timeout: float = 5.0,
    sink=None,
    stop=None,
    on_rearm=None,
) -> SessionResult:
    """Run one session. on_rearm, if given, keeps the connection after the
    device ends a transfer and is called each time the session goes back to
    waiting for the next recording."""
    runner = _Runner(
        link,
        decoder,
        deadline,
        pcm_timeout,
        command_timeout,
        sink=sink,
        stop=stop,
        on_rearm=on_rearm,
    )
    return await runner.run()
