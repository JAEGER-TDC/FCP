"""
dne_target.py — FCP → DNE binary framing protocol.

Packet wire format (little-endian):
  [0xAA] [length: u8] [payload: <length> bytes] [CRC16-CCITT: u16-LE]

Payload layout (STRUCT_FORMAT = "<6f3BQ", 35 bytes):
  azimuth        f   measured azimuth  (deg or rad, matches DNN units)
  elevation      f   measured elevation
  range          f   measured range
  azimuth_d      f   azimuth rate
  elevation_d    f   elevation rate
  range_d        f   range rate
  fire           B   0 = track only, 1 = fire
  state          B   1 = track, 2 = engage
  hit_confirm    B   0 = in-progress, 1 = kill confirmed
  time           Q   epoch milliseconds at packet build time
"""

import struct
import time as _time
from dataclasses import dataclass
from typing import ClassVar

HEADER: int = 0xAA


# ---------------------------------------------------------------------------
# CRC
# ---------------------------------------------------------------------------

def crc16_ccitt(data: bytes, poly: int = 0x1021, init: int = 0xFFFF) -> int:
    crc = init
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ poly
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

@dataclass
class Target:
    """Targeting packet sent from FCP to DNE over serial."""
    azimuth:         float = 0.0
    elevation:       float = 0.0
    range:           float = 0.0
    azimuth_d:       float = 0.0
    elevation_d:     float = 0.0
    range_d:         float = 0.0
    fire:            int   = 0
    state:           int   = 1
    hit_confirmation: int  = 0
    time:            int   = 0

    STRUCT_FORMAT: ClassVar[str] = "<6f3BQ"
    SIZE:          ClassVar[int] = struct.calcsize("<6f3BQ")  # 35 bytes

    def pack(self) -> bytes:
        return struct.pack(
            self.STRUCT_FORMAT,
            self.azimuth,
            self.elevation,
            self.range,
            self.azimuth_d,
            self.elevation_d,
            self.range_d,
            self.fire,
            self.state,
            self.hit_confirmation,
            self.time,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "Target":
        values = struct.unpack(cls.STRUCT_FORMAT, data)
        return cls(*values)


# ---------------------------------------------------------------------------
# Packet builder
# ---------------------------------------------------------------------------

def make_packet(msg: Target, header: int = HEADER) -> bytes:
    """Wrap a Target in the framed binary packet the DNE expects."""
    payload = msg.pack()
    size    = len(payload)
    body    = struct.pack("<B", size) + payload
    crc     = crc16_ccitt(body)
    return struct.pack("<B", header) + body + struct.pack("<H", crc)


# ---------------------------------------------------------------------------
# Packet receiver (parses DNE echo/status packets back to FCP)
# ---------------------------------------------------------------------------

class PacketReceiver:
    """Stateful byte-by-byte parser for DNE → FCP echo packets."""

    def __init__(self) -> None:
        self._state     = "WAIT_HEADER"
        self._length    = 0
        self._buffer    = bytearray()
        self._crc_bytes = bytearray()

    def process_byte(self, byte: int):
        """Feed one byte.  Returns a Target when a valid complete packet arrives, else None."""
        if self._state == "WAIT_HEADER":
            if byte == HEADER:
                self._state = "WAIT_LENGTH"

        elif self._state == "WAIT_LENGTH":
            self._length = byte
            self._buffer.clear()
            self._crc_bytes.clear()
            self._state = "WAIT_PAYLOAD"

        elif self._state == "WAIT_PAYLOAD":
            self._buffer.append(byte)
            if len(self._buffer) >= self._length:
                self._state = "WAIT_CRC"

        elif self._state == "WAIT_CRC":
            self._crc_bytes.append(byte)
            if len(self._crc_bytes) >= 2:
                recv_crc = struct.unpack("<H", self._crc_bytes)[0]
                body     = bytes([self._length]) + self._buffer
                calc_crc = crc16_ccitt(body)
                self._state = "WAIT_HEADER"
                if recv_crc == calc_crc:
                    return Target.unpack(bytes(self._buffer))
                print(f"[DNE] CRC mismatch: got {recv_crc:#06x}, expected {calc_crc:#06x}")
                return None

        return None
