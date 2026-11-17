"""In-memory P-256 ECDH, HKDF-SHA256, and AES-CTR for one diagnostic session.

Salt and info are the three bytes 01 02 03. The per-file plaintext must start
with the 14-byte marker soundcored3200. Keys are not written anywhere.
"""

from __future__ import annotations

import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

FILE_MAGIC = b"soundcored3200"
_HKDF_SALT = bytes((1, 2, 3))
_HKDF_INFO = bytes((1, 2, 3))


def derive_session_key(shared: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    ).derive(shared)


def aes_ctr(key: bytes, iv: bytes, data: bytes) -> bytes | None:
    if len(key) not in (16, 24, 32) or len(iv) != 16:
        return None
    try:
        decryptor = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
        return decryptor.update(data) + decryptor.finalize()
    except Exception:
        return None


def _wipe(buf: bytearray | None) -> None:
    if not buf:
        return
    for index in range(len(buf)):
        buf[index] = 0


class SessionCrypto:
    def __init__(self) -> None:
        self._private = ec.generate_private_key(ec.SECP256R1())
        self._session: bytearray | None = None
        self._file_key: bytearray | None = None
        self._nonce12: bytes | None = None

    def public_uncompressed(self) -> bytes:
        return self._private.public_key().public_bytes(
            Encoding.X962,
            PublicFormat.UncompressedPoint,
        )

    def complete(self, device_public: bytes, device_shared: bytes) -> bool:
        if len(device_public) != 65 or device_public[0] != 0x04 or len(device_shared) != 32:
            return False
        try:
            peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), device_public)
            shared = self._private.exchange(ec.ECDH(), peer)
        except Exception:
            return False
        if len(shared) != 32 or not hmac.compare_digest(shared, device_shared):
            return False
        derived = derive_session_key(shared)
        self._session = bytearray(derived)
        return True

    def install_file_key(self, encrypted: bytes, session_nonce: bytes, nonce: bytes) -> bool:
        if self._session is None or len(session_nonce) != 16 or len(nonce) < 12:
            return False
        plain_bytes = aes_ctr(bytes(self._session), session_nonce, encrypted)
        if plain_bytes is None:
            return False
        plain = bytearray(plain_bytes)
        try:
            if len(plain) < 46 or bytes(plain[:14]) != FILE_MAGIC:
                return False
            self._file_key = bytearray(plain[14:46])
            self._nonce12 = bytes(nonce[:12])
            return True
        finally:
            _wipe(plain)

    def decrypt_chunk(self, sequence: int, data: bytes) -> bytes | None:
        if self._file_key is None or self._nonce12 is None or len(data) != 160:
            return None
        counter = (sequence * 10) & 0xFFFFFFFF
        iv = self._nonce12 + counter.to_bytes(4, "big")
        return aes_ctr(bytes(self._file_key), iv, data)

    def wipe(self) -> None:
        _wipe(self._session)
        _wipe(self._file_key)
        self._session = None
        self._file_key = None
        self._nonce12 = None
        self._private = None
