"""
dne_jog_test.py — Manual DNE bench/field test tool.

Standalone from the FCP GUI: jogs azimuth/elevation with the arrow keys and
toggles the laser with spacebar, so you can confirm the DNE link is alive
and moving correctly without needing the DNN or the full FCP running.

Terminal UI (curses) by design — a separate GUI window depends on the
window manager handing it real keyboard focus, which WSL2/WSLg does not
reliably do. curses reads keys directly from the terminal you're already
typing into, so there's no focus-stealing problem at all.

Baud is 115200 — confirmed directly against the effector team's current
reference script (received 2026-06-17), which also confirmed the message
field set: azimuth/elevation/range/az_d/el_d/range_d/fire/state/
hit_confirmation/time. That matches the "crc" protocol below field-for-
field, so it's the default. ("legacy" was an earlier guess based on a
stale script already in this repo — simulators/fcp/sending_to_arduino.py,
9600 baud, no CRC, no hit_confirmation/time fields — kept only as a
fallback in case the real wire framing turns out not to use CRC after all.)

  crc    — 35-byte payload + CRC16, "<6f3BQ" struct, 115200 baud. What the
           FCP app, dne_sim.py, and (per the reference script's field set)
           the real DNE board all use.
  legacy — 26-byte payload, NO CRC, "<6f2B" struct, 9600 baud. Fallback only.

NOTE: the reference script also performs a calibration handshake before
normal tracking — sending calibration messages and waiting for an ACK
until azimuth reaches 222° — before the Arduino responds normally. This
tool does not yet do that; if the real board requires it, expect
UNHEALTHY / no movement until that handshake is implemented.

The same "healthy = received an echoed packet within 3s" rule as the FCP
itself is used, so a "HEALTHY" reading here means the FCP will also see
it as healthy (once the FCP is talking the same protocol).

Run from the repo root:
    poetry run python fcp/dne_jog_test.py                                  # real hardware, crc+115200
    poetry run python fcp/dne_jog_test.py --port /dev/ttyACM1
    poetry run python fcp/dne_jog_test.py --port socket://127.0.0.1:6000   # against dne_sim
    poetry run python fcp/dne_jog_test.py --protocol legacy --baud 9600    # fallback if crc doesn't work

Not sure which port to use?
    poetry run python fcp/dne_jog_test.py --list-ports

Controls:
    Up/Down     elevation +/- step
    Left/Right  azimuth   +/- step
    Space       toggle laser fire on/off
    +/-         increase/decrease step size
    r           reset azimuth/elevation to 0
    q           quit
"""

import argparse
import configparser
import curses
import glob
import importlib.util
import os
import threading
import time

import serial
import serial.tools.list_ports

_HEALTH_TIMEOUT = 3.0   # seconds of silence before we call the link unhealthy
_SEND_HZ = 10.0         # continuous send rate, matches the FCP's targeting cadence

_LEGACY_PROTOCOL_PATH = os.path.join(os.path.dirname(__file__), '..', 'protocol', 'dne_target.py')


def _load_protocol_module(name: str):
    """Load either protocol implementation unambiguously by file path —
    NOT via `import protocol.dne_target`, which resolves differently
    depending on sys.path order and has caused real bugs in this repo
    before (the legacy and crc modules share the same dotted name)."""
    if name == 'crc':
        path = os.path.join(os.path.dirname(__file__), 'protocol', 'dne_target.py')
    else:
        path = _LEGACY_PROTOCOL_PATH
    spec = importlib.util.spec_from_file_location(f'_dne_protocol_{name}', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _print_port_listing():
    """Print everything that might be the DNE, with enough identifying info
    to tell devices apart — and the stable by-id path to actually use, since
    a bare /dev/ttyACMx index can silently point at a different physical
    board depending on attach order."""
    print('\n=== Serial devices currently visible to this machine ===')
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print('  (none found — is the DNE attached? On WSL2, check '
              '`usbipd attach --wsl --busid <id>` succeeded on the Windows side.)')
    for p in ports:
        print(f'  {p.device}')
        print(f'      description : {p.description}')
        print(f'      manufacturer: {p.manufacturer}')
        print(f'      vid:pid     : {p.vid:04x}:{p.pid:04x}' if p.vid and p.pid else '      vid:pid     : ?')
        print(f'      serial_number: {p.serial_number}')

    by_id_dir = '/dev/serial/by-id'
    by_id_links = sorted(glob.glob(os.path.join(by_id_dir, '*'))) if os.path.isdir(by_id_dir) else []
    print(f'\n=== Stable by-id paths ({by_id_dir}) — prefer these over /dev/ttyACMx ===')
    if not by_id_links:
        print('  (none — only appears once a device is attached)')
    for link in by_id_links:
        target = os.path.realpath(link)
        print(f'  {link}\n      -> {target}')

    print('\n=== Simulator (no hardware) ===')
    print('  socket://127.0.0.1:6000   — requires simulators/dne_sim/dne_sim_app.py running')

    default_port, _ = _load_default_port_baud()
    print(f'\nCurrent config.ini default DNE port: {default_port}')
    if by_id_links and default_port not in by_id_links and not default_port.startswith('socket://'):
        print('  NOTE: this is not a by-id path — it may point at the wrong device '
              'if attach order changes.')
    print()


def _load_default_port_baud() -> tuple[str, int]:
    cfg_path = os.path.join(os.path.dirname(__file__), 'cfg', 'config.ini')
    parser = configparser.ConfigParser()
    parser.read(cfg_path)
    port = parser.get('DNE.serial', 'port', fallback='/dev/ttyACM1')
    baud = parser.getint('DNE.serial', 'baudrate', fallback=115200)
    return port, baud


class DNEJogTest:
    """Connection + state. UI-agnostic — run() drives it with curses."""

    def __init__(self, port: str, baud: int, protocol_name: str, protocol_mod):
        self._port = port
        self._baud = baud
        self._protocol_name = protocol_name
        self._proto = protocol_mod
        self._ser: serial.SerialBase | None = None
        self._ser_lock = threading.Lock()
        self._stop_event = threading.Event()

        self._az = 0.0
        self._el = 0.0
        self._range = 25.0
        self._fire = False
        self._step = 2.0

        self._healthy = False
        self._last_echo = 0.0
        self._last_sent = 0.0
        self._packets_sent = 0
        self._packets_recv = 0
        self._connect_error: str | None = None

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------

    def adjust(self, az: float = 0.0, el: float = 0.0):
        self._az += az * self._step
        self._el += el * self._step
        self._az = max(-180.0, min(180.0, self._az))
        self._el = max(-90.0,  min(90.0,  self._el))
        self._send_packet()

    def adjust_step(self, delta: float):
        self._step = max(0.5, min(45.0, self._step + delta))

    def toggle_fire(self):
        self._fire = not self._fire
        self._send_packet()

    def reset(self):
        self._az = 0.0
        self._el = 0.0
        self._send_packet()

    def quit(self):
        self._stop_event.set()
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Serial connection + send/receive loops
    # ------------------------------------------------------------------

    def connect(self):
        try:
            self._ser = serial.serial_for_url(self._port, baudrate=self._baud, timeout=1.0)
        except Exception as e:
            self._connect_error = str(e)
            self._ser = None
            return

        threading.Thread(target=self._recv_loop, daemon=True).start()
        threading.Thread(target=self._send_loop, daemon=True).start()

    def _recv_loop(self):
        receiver = self._proto.PacketReceiver()
        while not self._stop_event.is_set():
            try:
                byte = self._ser.read(1)
                if self._stop_event.is_set():
                    break
                if not byte:
                    if self._healthy and time.time() - self._last_echo > _HEALTH_TIMEOUT:
                        self._healthy = False
                    continue
                result = receiver.process_byte(byte[0])
                if result is not None:
                    self._last_echo = time.time()
                    self._healthy = True
                    self._packets_recv += 1
            except Exception:
                if self._stop_event.is_set():
                    break
                time.sleep(0.5)

    def _send_packet(self):
        if self._ser is None:
            return
        fire = 1 if self._fire else 0
        # Per myStateMachine.h on the real DNE firmware: IDLE=0, CALIBRATE=1,
        # TRACKING=2, ENGAGE=3. Laser fire is controlled purely by the `fire`
        # field regardless of state, so TRACKING is correct for jogging
        # whether or not the laser is on — sending state=1 (our old default)
        # actually puts the board in CALIBRATE mode instead, which treats
        # az/el as a literal calibration target with 222 deg as a special
        # "zero this axis" sentinel.
        state_cmd = 2
        try:
            if self._protocol_name == 'crc':
                t = self._proto.Target(self._az, self._el, self._range, 0.0, 0.0, 0.0,
                                       fire, state_cmd, time=int(time.time() * 1000))
            else:
                t = self._proto.Target(self._az, self._el, self._range, 0.0, 0.0, 0.0,
                                       fire, state_cmd)
            with self._ser_lock:
                self._ser.write(self._proto.make_packet(t))
            self._packets_sent += 1
            self._last_sent = time.time()
        except Exception:
            pass

    def _send_loop(self):
        period = 1.0 / _SEND_HZ
        while not self._stop_event.is_set():
            self._send_packet()
            time.sleep(period)


def _run_curses(stdscr, app: DNEJogTest):
    curses.curs_set(0)       # hide the text cursor
    stdscr.nodelay(True)     # non-blocking getch
    stdscr.keypad(True)      # decode arrow-key escape sequences into KEY_UP etc.

    while not app._stop_event.is_set():
        ch = stdscr.getch()
        if ch == curses.KEY_UP:
            app.adjust(el=+1)
        elif ch == curses.KEY_DOWN:
            app.adjust(el=-1)
        elif ch == curses.KEY_LEFT:
            app.adjust(az=-1)
        elif ch == curses.KEY_RIGHT:
            app.adjust(az=+1)
        elif ch == ord(' '):
            app.toggle_fire()
        elif ch in (ord('+'), ord('=')):
            app.adjust_step(+1.0)
        elif ch == ord('-'):
            app.adjust_step(-1.0)
        elif ch == ord('r'):
            app.reset()
        elif ch == ord('q'):
            app.quit()
            break

        _draw(stdscr, app)
        time.sleep(0.03)


def _draw(stdscr, app: DNEJogTest):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    def line(y, text, attr=0):
        if 0 <= y < h:
            stdscr.addnstr(y, 2, text, max(0, w - 4), attr)

    line(0, 'DNE Jog Test', curses.A_BOLD)
    line(1, f'Port: {app._port} @ {app._baud}  [{app._protocol_name} protocol]')

    if app._healthy:
        line(3, '● HEALTHY', curses.A_BOLD)
    else:
        line(3, '○ UNHEALTHY', curses.A_BOLD)

    line(5,  f'Azimuth (deg)  : {app._az:+.1f}')
    line(6,  f'Elevation (deg): {app._el:+.1f}')
    line(7,  f'Range (m)      : {app._range:.1f}')
    line(8,  f'Laser          : {"ON" if app._fire else "OFF"}',
        curses.A_BOLD if app._fire else 0)
    line(9,  f'Step (deg)     : {app._step:.1f}')

    age = time.time() - app._last_echo if app._last_echo else None
    line(11, f'Packets sent   : {app._packets_sent}')
    line(12, f'Packets echoed : {app._packets_recv}')
    line(13, f'Last echo age  : {age:.1f}s' if age is not None else 'Last echo age  : —')

    line(h - 5, 'Up/Down: elevation    Left/Right: azimuth')
    line(h - 4, 'Space: toggle laser    +/-: step size')
    line(h - 3, 'r: reset az/el to 0    q: quit')

    stdscr.refresh()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    default_port, _ = _load_default_port_baud()
    ap.add_argument('--port', default=default_port,
                    help=f'Serial port or socket:// URL (default from config.ini: {default_port})')
    ap.add_argument('--baud', type=int, default=115200,
                    help='Baud rate (default 115200 — confirmed against the current '
                         'effector-team reference script, both for real hardware and crc)')
    ap.add_argument('--protocol', choices=['auto', 'legacy', 'crc'], default='auto',
                    help="'crc' = 35-byte CRC, 10-field Target (FCP app / dne_sim) — matches "
                         "the field set used by the effector team's current "
                         "ReceivedFCPCalMessage. 'legacy' = older 26-byte no-CRC, 8-field "
                         "format from a stale reference script — kept only as a fallback. "
                         "'auto' (default) picks crc.")
    ap.add_argument('--list-ports', action='store_true',
                    help='List visible serial devices and stable by-id paths, then exit')
    args = ap.parse_args()

    if args.list_ports:
        _print_port_listing()
        return

    protocol_name = args.protocol
    if protocol_name == 'auto':
        protocol_name = 'crc'
    baud = args.baud
    protocol_mod = _load_protocol_module(protocol_name)

    app = DNEJogTest(args.port, baud, protocol_name, protocol_mod)
    app.connect()
    if app._ser is None:
        print(f'Failed to connect to {args.port}: {app._connect_error}')
        _print_port_listing()
        return

    print(f'Connected to DNE on {args.port} @ {baud} [{protocol_name} protocol]')
    try:
        curses.wrapper(_run_curses, app)
    except KeyboardInterrupt:
        app.quit()


if __name__ == '__main__':
    main()
