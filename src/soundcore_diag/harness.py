"""In-memory link used by offline tests. It does not import a Bluetooth stack."""

from __future__ import annotations

import asyncio

from soundcore_diag.protocol import checksum


class LinkClosed(Exception):
    pass


def rx_frame(cmd_type: int, cmd_id: int, payload: bytes = b"", status: int = 1) -> bytes:
    body_len = 10 + len(payload)
    out = bytearray(b"\x09\xff\x00\x00")
    out.append(status & 0xFF)
    out.append(cmd_type & 0xFF)
    out.append(cmd_id & 0xFF)
    out.append(body_len & 0xFF)
    out.append((body_len >> 8) & 0xFF)
    out.extend(payload)
    out.append(checksum(out))
    return bytes(out)


class MemoryLink:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.disconnects = 0
        self.closed = False
        self.overflow = False

    async def write(self, frame: bytes) -> None:
        if self.closed:
            raise LinkClosed()
        self.writes.append(bytes(frame))

    def push(self, data: bytes) -> None:
        self.queue.put_nowait(bytes(data))

    async def disconnect(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.disconnects += 1
        self.queue.put_nowait(None)
