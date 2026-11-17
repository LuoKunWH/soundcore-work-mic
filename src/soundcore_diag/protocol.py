"""D3200 frame layout used by this diagnostic.

The byte layout follows the MIT-licensed notes and implementation in
tacshi/Soundcore at d296a1c5c0645797ff7cd3b55e93477a99820857
(Copyright (c) 2026 Rocky Shi). This module only builds the four transmit
commands the diagnostic is allowed to send.

Transmit:
  01/01  empty payload, device info
  2E/01  65-byte uncompressed P-256 public key
  1A/07  offset 0, realtime flag 1, file id chosen by the caller
  1A/11  payload 00, stop the transfer (not the physical recording)

The 5-byte firmware field is returned unchanged. It is not a full version.
"""

from __future__ import annotations

from dataclasses import dataclass

TX_MAGIC = b"\x08\xee\x00\x00\x00"
RX_MAGIC = b"\x09\xff\x00\x00"
MAX_FRAME = 2048

ALLOWED_TX = {
    (0x01, 0x01),
    (0x2E, 0x01),
    (0x1A, 0x07),
    (0x1A, 0x11),
}


class ProtocolError(Exception):
    """A frame is not one this diagnostic is allowed to send or parse."""


def checksum(data: bytes | bytearray) -> int:
    return sum(data) & 0xFF


def _validate_tx(cmd_type: int, cmd_id: int, payload: bytes) -> None:
    pair = (cmd_type & 0xFF, cmd_id & 0xFF)
    if pair not in ALLOWED_TX:
        raise ProtocolError("command is not allowed")
    if pair == (0x01, 0x01):
        if payload:
            raise ProtocolError("device info payload must be empty")
        return
    if pair == (0x2E, 0x01):
        if len(payload) != 65 or payload[0] != 0x04:
            raise ProtocolError("handshake public key must be 65 uncompressed bytes")
        return
    if pair == (0x1A, 0x07):
        if len(payload) != 9 or payload[8] != 1:
            raise ProtocolError("realtime transfer requires a 9-byte payload and flag 1")
        offset = int.from_bytes(payload[0:4], "little")
        file_id = int.from_bytes(payload[4:8], "little")
        if offset != 0 or file_id == 0:
            raise ProtocolError("realtime transfer offset must be 0 and file id nonzero")
        return
    if pair == (0x1A, 0x11):
        if payload != b"\x00":
            raise ProtocolError("transfer stop payload must be 0x00")
        return
    raise ProtocolError("command is not allowed")


def encode(cmd_type: int, cmd_id: int, payload: bytes = b"") -> bytes:
    payload = bytes(payload)
    _validate_tx(cmd_type, cmd_id, payload)
    body_len = 10 + len(payload)
    out = bytearray(TX_MAGIC)
    out.append(cmd_type & 0xFF)
    out.append(cmd_id & 0xFF)
    out.append(body_len & 0xFF)
    out.append((body_len >> 8) & 0xFF)
    out.extend(payload)
    out.append(checksum(out))
    return bytes(out)


def device_info_request() -> bytes:
    return encode(0x01, 0x01, b"")


def handshake_request(public_key: bytes) -> bytes:
    return encode(0x2E, 0x01, public_key)


def realtime_request(file_id: int) -> bytes:
    payload = (0).to_bytes(4, "little") + int(file_id).to_bytes(4, "little") + b"\x01"
    return encode(0x1A, 0x07, payload)


def transfer_stop_request() -> bytes:
    return encode(0x1A, 0x11, b"\x00")


def assert_tx_frame(frame: bytes) -> None:
    if len(frame) < 10 or frame[:5] != TX_MAGIC:
        raise ProtocolError("not a diagnostic transmit frame")
    if checksum(frame[:-1]) != frame[-1]:
        raise ProtocolError("transmit checksum mismatch")
    _validate_tx(frame[5], frame[6], frame[9:-1])


@dataclass(frozen=True)
class Packet:
    raw: bytes
    status: int
    cmd_type: int
    cmd_id: int
    payload: bytes

    @property
    def rejected(self) -> bool:
        return self.payload == b"\xff"

    @property
    def success(self) -> bool:
        return (not self.rejected) and ((self.status & 0x0F) == 1)

    @classmethod
    def from_frame(cls, frame: bytes) -> "Packet":
        payload = bytes(frame[9:-1]) if len(frame) > 10 else b""
        return cls(
            raw=bytes(frame),
            status=frame[4],
            cmd_type=frame[5],
            cmd_id=frame[6],
            payload=payload,
        )


def drain_packets(buf: bytearray) -> list[Packet]:
    """Take complete, checksum-valid RX frames out of buf. Incomplete bytes stay."""
    out: list[Packet] = []
    while True:
        start = buf.find(RX_MAGIC)
        if start < 0:
            if len(buf) > 3:
                del buf[:-3]
            return out
        if start:
            del buf[:start]
        if len(buf) < 10:
            return out
        total = buf[7] | (buf[8] << 8)
        if total < 10 or total > MAX_FRAME:
            del buf[0]
            continue
        if len(buf) < total:
            return out
        frame = bytes(buf[:total])
        del buf[:total]
        if checksum(frame[:-1]) == frame[-1]:
            out.append(Packet.from_frame(frame))


def _battery_percent(raw: int) -> int | None:
    if 0 <= raw <= 9:
        return (raw + 1) * 10
    if 10 <= raw <= 100:
        return raw
    return None


def _field5(data: bytes) -> str:
    if len(data) != 5:
        return ""
    if all(32 <= byte < 127 for byte in data):
        return data.decode("ascii").rstrip("\x00").strip()
    return data.hex()


@dataclass(frozen=True)
class DeviceInfo:
    firmware_field: str
    recording_byte: int | None
    mic_battery_percent: int | None
    case_battery_percent: int | None


def parse_device_info(payload: bytes) -> DeviceInfo | None:
    """Parse the device-info payload. The serial number is not retained."""
    if len(payload) < 8:
        return None
    recording = payload[50] if len(payload) > 50 else None
    case_battery = _battery_percent(payload[38]) if len(payload) > 38 else None
    return DeviceInfo(
        firmware_field=_field5(payload[3:8]),
        recording_byte=recording,
        mic_battery_percent=_battery_percent(payload[1]),
        case_battery_percent=case_battery,
    )


def parse_handshake(payload: bytes) -> tuple[bytes, bytes] | None:
    """Device public key and shared secret, both fully inside the payload."""
    if len(payload) < 97 or payload[0] != 0x04:
        return None
    return bytes(payload[0:65]), bytes(payload[65:97])


@dataclass(frozen=True)
class FileHead:
    file_id: int
    file_size: int
    nonce: bytes
    encrypted_file_key: bytes
    session_nonce: bytes
    error_code: int


def parse_file_head(payload: bytes) -> FileHead | None:
    if len(payload) < 87:
        return None
    return FileHead(
        file_id=int.from_bytes(payload[0:4], "little"),
        file_size=int.from_bytes(payload[4:8], "little"),
        nonce=bytes(payload[8:24]),
        encrypted_file_key=bytes(payload[24:70]),
        session_nonce=bytes(payload[70:86]),
        error_code=payload[86],
    )


def parse_active_file_id(payload: bytes) -> int | None:
    """1A/06 payload: little-endian file id in the first four bytes."""
    if len(payload) < 4:
        return None
    file_id = int.from_bytes(payload[0:4], "little")
    if file_id <= 0:
        return None
    return file_id


def parse_slices(frame: bytes) -> list[tuple[int, bytes]]:
    """166-byte units from a full RX frame: seq, flags, 160 data, pad."""
    out: list[tuple[int, bytes]] = []
    limit = len(frame) - 1
    index = 9
    while limit - index >= 165:
        seq = int.from_bytes(frame[index : index + 4], "little")
        index += 5
        data = bytes(frame[index : index + 160])
        index += 160
        if index < limit:
            index += 1
        out.append((seq, data))
    return out
