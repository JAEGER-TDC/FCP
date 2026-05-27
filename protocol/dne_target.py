"""
DNE serial packet protocol — shared by FCP and DNE simulator.

Ported from simulators/fcp/sending_to_arduino.py and updated to match
the DNN team's revised spec (C:/GitHub/DNN, myTelemetry.h / SerialIO.py).

Packet framing FCP → DNE:
    [0xAA] [SIZE] [payload: 35 bytes] [CRC-16 LE]
     header  len   <6f3BQ>

Packet framing DNE → FCP (health, no CRC):
    [0xAA] [SIZE] [payload: 2 bytes]
     header  len   <2B>

Packet framing DNE → FCP (debug echo, with CRC):
    [0xAA] [SIZE] [payload: 35 bytes] [CRC-16 LE]
     header  len   <6f3BQ>
"""
import struct
from dataclasses import dataclass, field
from typing import ClassVar

HEADER: int = 0xAA


def crc16_ccitt(data: bytes, poly: int = 0x1021, init: int = 0xFFFF) -> int:
    """CRC-16-CCITT over data. Matches myTelemetry.cpp crc16_ccitt()."""
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


@dataclass
class Target:
    azimuth: float
    elevation: float
    range: float
    azimuth_d: float
    elevation_d: float
    range_d: float
    fire: int            # uint8: 0 = track only, 1 = fire laser
    state: int           # uint8: IDLE=0, CAL=1, TRACKING=2, ENGAGE=3
    hit_confirmation: int = 0  # uint8: 1 = hit confirmed, 0 = normal
    time: int = 0        # uint64: FCP timestamp in microseconds

    STRUCT_FORMAT: ClassVar[str] = "<6f3BQ"
    SIZE: ClassVar[int] = struct.calcsize(STRUCT_FORMAT)  # 35

    def pack(self) -> bytes:
        return struct.pack(
            self.STRUCT_FORMAT,
            float(self.azimuth),
            float(self.elevation),
            float(self.range),
            float(self.azimuth_d),
            float(self.elevation_d),
            float(self.range_d),
            int(self.fire),
            int(self.state),
            int(self.hit_confirmation),
            int(self.time),
        )

    @classmethod
    def unpack(cls, data: bytes) -> "Target":
        return cls(*struct.unpack(cls.STRUCT_FORMAT, data))


@dataclass
class DNEHealth:
    am_i_healthy: int  # uint8: 1=HEALTHY, 2=BAD_MSG, 3=WRONG_SIZE, 4=TIMEOUT
    laser_firing: int  # uint8: 0 or 1

    STRUCT_FORMAT: ClassVar[str] = "<2B"
    SIZE: ClassVar[int] = struct.calcsize(STRUCT_FORMAT)  # 2

    @classmethod
    def unpack(cls, data: bytes) -> "DNEHealth":
        return cls(*struct.unpack(cls.STRUCT_FORMAT, data))


def make_packet(target: Target) -> bytes:
    """Wrap a Target in [0xAA][size][payload][CRC-16 LE] framing."""
    payload = target.pack()
    body = struct.pack("<B", Target.SIZE) + payload
    crc = crc16_ccitt(body)
    return struct.pack("<B", HEADER) + body + struct.pack("<H", crc)


def make_health_packet(health: DNEHealth) -> bytes:
    """Wrap a DNEHealth in [0xAA][size][payload] framing (no CRC, matching hardware)."""
    payload = struct.pack(DNEHealth.STRUCT_FORMAT, health.am_i_healthy, health.laser_firing)
    return struct.pack("<BB", HEADER, DNEHealth.SIZE) + payload


class PacketReceiver:
    """Byte-by-byte state machine for parsing framed packets from the DNE.

    Handles two response types:
      - DNEHealth (2-byte payload, no CRC): returned as DNEHealth
      - Target debug echo (35-byte payload, with CRC): returned as Target

    Feed one byte at a time via process_byte(). Returns DNEHealth, Target,
    or None on each call.
    """

    def __init__(self):
        self._state = "WAIT_HEADER"
        self._length = 0
        self._buffer = bytearray()
        self._crc_buf = bytearray()

    def process_byte(self, byte: int) -> "DNEHealth | Target | None":
        if self._state == "WAIT_HEADER":
            if byte == HEADER:
                self._state = "WAIT_LENGTH"

        elif self._state == "WAIT_LENGTH":
            self._length = byte
            self._buffer.clear()
            self._crc_buf.clear()
            if self._length in (DNEHealth.SIZE, Target.SIZE):
                self._state = "WAIT_PAYLOAD"
            else:
                self._state = "WAIT_HEADER"

        elif self._state == "WAIT_PAYLOAD":
            self._buffer.append(byte)
            if len(self._buffer) >= self._length:
                if self._length == DNEHealth.SIZE:
                    # Health message: no CRC, parse immediately
                    result = DNEHealth.unpack(bytes(self._buffer))
                    self._state = "WAIT_HEADER"
                    return result
                else:
                    # Debug echo: wait for 2-byte CRC
                    self._state = "WAIT_CRC"

        elif self._state == "WAIT_CRC":
            self._crc_buf.append(byte)
            if len(self._crc_buf) >= 2:
                recv_crc = struct.unpack("<H", self._crc_buf)[0]
                body = bytes([self._length]) + bytes(self._buffer)
                calc_crc = crc16_ccitt(body)
                self._state = "WAIT_HEADER"
                if recv_crc == calc_crc:
                    return Target.unpack(bytes(self._buffer))
                # CRC mismatch — drop packet silently

        return None
