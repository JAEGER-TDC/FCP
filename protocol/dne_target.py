"""
DNE serial packet protocol — shared by FCP and DNE simulator.

Ported verbatim from simulators/fcp/sending_to_arduino.py (effector team).
Update here if the effector team changes their struct.

Packet framing (both directions):
    [0xAA] [0x1A] [26-byte Target payload]
     header  len
"""
import struct
from dataclasses import dataclass
from typing import ClassVar

HEADER: int = 0xAA


@dataclass
class Target:
    azimuth: float
    elevation: float
    range: float
    azimuth_d: float
    elevation_d: float
    range_d: float
    fire: int   # uint8: 0 = track only, 1 = fire laser
    state: int  # uint8: 1 = armed/tracking, 2 = engage

    STRUCT_FORMAT: ClassVar[str] = "<6f2B"
    SIZE: ClassVar[int] = struct.calcsize(STRUCT_FORMAT)  # 26

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
        )

    @classmethod
    def unpack(cls, data: bytes) -> "Target":
        return cls(*struct.unpack(cls.STRUCT_FORMAT, data))


def make_packet(target: Target) -> bytes:
    """Wrap a Target in [0xAA][size][payload] framing (28 bytes total)."""
    return struct.pack("<BB", HEADER, Target.SIZE) + target.pack()


class PacketReceiver:
    """Byte-by-byte state machine for parsing framed Target packets.

    Feed one byte at a time via process_byte().  Returns a Target when a
    complete, valid packet has been received; otherwise returns None.
    """

    def __init__(self):
        self.state = "WAIT_HEADER"
        self.length = 0
        self.buffer = bytearray()

    def process_byte(self, byte: int) -> "Target | None":
        if self.state == "WAIT_HEADER":
            if byte == HEADER:
                self.state = "WAIT_LENGTH"

        elif self.state == "WAIT_LENGTH":
            self.length = byte
            if self.length == Target.SIZE:
                self.buffer.clear()
                self.state = "WAIT_PAYLOAD"
            else:
                self.state = "WAIT_HEADER"

        elif self.state == "WAIT_PAYLOAD":
            self.buffer.append(byte)
            if len(self.buffer) >= self.length:
                target = Target.unpack(bytes(self.buffer))
                self.state = "WAIT_HEADER"
                return target

        return None
