import serial
import struct
import time
from dataclasses import dataclass
from typing import ClassVar
import math
import time
import matplotlib.pyplot as plt


class TargetTruthSimulator:
    def __init__(self):
        self.last_update = time.perf_counter()
        self.t = 0.0
        self.stopped = False

        # -------- Initial position --------
        self.x0 = 90.0
        self.y0 = 90.0

        # -------- Constant velocity --------
        self.vx = -3.0
        self.vy = -4.0

        # -------- Lateral oscillation --------
        self.A = 10.0
        self.f = 0.1

        # -------- Previous position --------
        self.x_prev = self.x0
        self.y_prev = self.y0

    def update(self):
        now = time.perf_counter()
        dt = now - self.last_update
        self.last_update = now

        if not self.stopped:
            self.t += dt

        # -------- Current position --------
        x = (
            self.x0
            + self.vx * self.t
            + self.A * math.sin(2.0 * math.pi * self.f * self.t)
        )
        y = self.y0 + self.vy * self.t

        # -------- Axis crossing detection --------
        if not self.stopped:
            crossed_y_axis = (self.x_prev * x) <= 0.0
            crossed_x_axis = (self.y_prev * y) <= 0.0
            if crossed_x_axis or crossed_y_axis:
                self.stopped = True

        # -------- Effective x velocity --------
        vx_eff = (
            self.vx
            + 2.0 * math.pi * self.f * self.A
            * math.cos(2.0 * math.pi * self.f * self.t)
        )

        # -------- Range and azimuth --------
        r = math.sqrt(x * x + y * y)
        az = math.degrees(math.atan2(y, x))

        # -------- Derivatives --------
        if self.stopped or r == 0.0:
            r_d = 0.0
            az_d = 0.0
        else:
            r_d = (x * vx_eff + y * self.vy) / r
            az_d = (
                (x * self.vy - y * vx_eff)
                / (r * r)
                * 180.0 / math.pi
            )

        # -------- Save previous position --------
        self.x_prev = x
        self.y_prev = y

        return {
            "azimuth": az,
            "range": r,
            "elevation": 0.0,
            "azimuth_d": az_d,
            "range_d": r_d,
            "elevation_d": 0.0,
        }


# ================== Protocol Constants ==================

HEADER: int = 0xAA
PORT: str = "COM3"
BAUDRATE: int = 9600

# ================== Target Struct ==================

@dataclass
class Target:
    azimuth: float
    elevation: float
    range: float
    azimuth_d: float
    elevation_d: float
    range_d: float
    fire: int  # uint8
    state: int

    STRUCT_FORMAT: ClassVar[str] = "<6f2B"
    SIZE: ClassVar[int] = struct.calcsize(STRUCT_FORMAT)

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
            int(self.state)
        )

    @classmethod
    def unpack(cls, data: bytes) -> "Target":
        values = struct.unpack(cls.STRUCT_FORMAT, data)
        return cls(*values)


# ================== Packet Helpers ==================

def make_packet(target: Target) -> bytes:
    payload = target.pack()
    return struct.pack("<BB", HEADER, Target.SIZE) + payload


# ================== Serial Receiver ==================

class PacketReceiver:
    def __init__(self):
        self.state = "WAIT_HEADER"
        self.length = 0
        self.buffer = bytearray()

    def process_byte(self, byte: int):
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


# ================== Main ==================

ser = serial.Serial(PORT, BAUDRATE, timeout=0)
receiver = PacketReceiver()

# tx_target_no_fire = Target(
#     azimuth=1.0,
#     elevation=2.0,
#     range=100.0,
#     azimuth_d=0.1,
#     elevation_d=0.2,
#     range_d=0.0,
#     fire=0
# )

tx_target_fire = Target(
    azimuth=1.0,
    elevation=2.0,
    range=100.0,
    azimuth_d=0.1,
    elevation_d=0.2,
    range_d=0.0,
    fire=1,
    state = 2
)

last_send = 0

print("Python serial interface running...")

fire_next_round = True
target_to_send = tx_target_fire

sim = TargetTruthSimulator()
last_send = 0.0
SEND_PERIOD = 0.1  # 10 Hz
run_look = True
time_hist = []
az_hist = []

t0 = time.perf_counter()


while not sim.stopped:
    now = time.time()

    truth = sim.update()
    t_now = time.perf_counter() - t0
    time_hist.append(t_now)
    az_hist.append(truth["azimuth"])

    # -------- Send at 10 Hz --------
    # if abs(now - last_send) >= 1.0:
    #     if fire_next_round:
    #         target_to_send = tx_target_fire
    #         fire_next_round = False
    #     else:
    #         target_to_send = tx_target_no_fire
    #         fire_next_round = True

        # packet = make_packet(target_to_send)
        # ser.write(packet)
        # last_send = now
        # print("We have now sent a packet")

    if now - last_send >= SEND_PERIOD:
        tx_target = Target(
            azimuth=truth["azimuth"],
            elevation=truth["elevation"],
            range=truth["range"],
            azimuth_d=truth["azimuth_d"],
            elevation_d=truth["elevation_d"],
            range_d=truth["range_d"],
            fire=1,
            state=2
        )

        ser.write(make_packet(tx_target))
        last_send = now
        print("Sent Packet")

    # -------- Receive & decode --------
    while ser.in_waiting:
        byte = ser.read(1)[0]
        result = receiver.process_byte(byte)

        if result:
            print("RX Target:")
            print(f"  Azimuth     : {result.azimuth:.3f}")
            print(f"  Elevation   : {result.elevation:.3f}")
            print(f"  Range       : {result.range:.3f}")
            print(f"  Azimuth_d   : {result.azimuth_d:.3f}")
            print(f"  Elevation_d : {result.elevation_d:.3f}")
            print(f"  Range_d     : {result.range_d:.3f}")
            print(f"  Fire        : {result.fire}")
            print(f"  State        : {result.state}")
            print("-" * 40)

    time.sleep(0.001)


ser.close()

plt.figure()
plt.plot(time_hist, az_hist)
plt.xlabel("Time [s]")
plt.ylabel("Azimuth [deg]")
plt.title("Target Azimuth Time History")
plt.grid(True)
plt.show()
