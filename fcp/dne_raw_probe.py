"""
dne_raw_probe.py — Raw serial probe for the DNE link, no protocol assumed.

dne_jog_test.py reported UNHEALTHY with zero echoed packets and no physical
movement on the DNE. Before guessing further about baud rate or protocol,
this answers the more basic question: is *anything* coming back over the
wire at all, at any common baud rate? And does sending raw bytes (not a
framed packet) provoke any reaction?

This intentionally has zero dependency on protocol/dne_target.py — it just
opens the port and dumps whatever bytes arrive, in hex, so a wiring/baud
problem can't be hidden behind a packet parser that's silently discarding
unrecognized bytes.

Run from the repo root:
    poetry run python fcp/dne_raw_probe.py
    poetry run python fcp/dne_raw_probe.py --port /dev/ttyACM0
    poetry run python fcp/dne_raw_probe.py --sweep          # try several common bauds
"""

import argparse
import configparser
import os
import time

import serial

_COMMON_BAUDS = [9600, 19200, 38400, 57600, 115200]


def _load_default_port() -> str:
    cfg_path = os.path.join(os.path.dirname(__file__), 'cfg', 'config.ini')
    parser = configparser.ConfigParser()
    parser.read(cfg_path)
    return parser.get('DNE.serial', 'port', fallback='/dev/ttyACM0')


def _probe_one_baud(port: str, baud: int, listen_s: float, send_junk: bool):
    print(f'\n--- {baud} baud ---')
    try:
        ser = serial.serial_for_url(port, baudrate=baud, timeout=0.2)
    except Exception as e:
        print(f'  failed to open: {e}')
        return

    # Give the board a moment in case it just reset on DTR toggle (common
    # Arduino behavior when a serial connection opens) and is still booting.
    time.sleep(0.3)
    ser.reset_input_buffer()

    total = bytearray()
    deadline = time.time() + listen_s
    sent_junk = False
    while time.time() < deadline:
        if send_junk and not sent_junk:
            # A handful of 0xAA header bytes plus newlines — harmless probe
            # bytes that might provoke a response from a sketch that expects
            # *some* framing, without assuming any specific protocol.
            try:
                ser.write(b'\xAA' * 8 + b'\r\n')
            except Exception:
                pass
            sent_junk = True
        chunk = ser.read(64)
        if chunk:
            total.extend(chunk)
    ser.close()

    if not total:
        print('  received: nothing')
    else:
        hex_str = ' '.join(f'{b:02x}' for b in total[:120])
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in total[:120])
        print(f'  received {len(total)} bytes:')
        print(f'    hex  : {hex_str}{" ..." if len(total) > 120 else ""}')
        print(f'    ascii: {ascii_str}{" ..." if len(total) > 120 else ""}')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default=_load_default_port())
    ap.add_argument('--baud', type=int, default=9600,
                    help='Single baud rate to test (ignored if --sweep is given)')
    ap.add_argument('--sweep', action='store_true',
                    help=f'Try each of {_COMMON_BAUDS} in turn')
    ap.add_argument('--listen', type=float, default=3.0,
                    help='Seconds to listen at each baud rate (default 3.0)')
    ap.add_argument('--send-junk', action='store_true',
                    help='Also write a few harmless probe bytes (0xAA x8 + CRLF) '
                         'at the start of each listen window, in case the board '
                         'only replies when it sees *something* arrive first')
    args = ap.parse_args()

    print(f'Probing {args.port}')
    bauds = _COMMON_BAUDS if args.sweep else [args.baud]
    for baud in bauds:
        _probe_one_baud(args.port, baud, args.listen, args.send_junk)

    print(
        '\nIf NOTHING came back at ANY baud rate (with or without --send-junk):\n'
        '  - the Arduino may not be transmitting on this line at all (by\n'
        '    design, or because the sketch never reached a transmitting state)\n'
        '  - or the physical TX wire from the board isn\'t actually connected\n'
        '  - or the sketch currently flashed on it isn\'t the DNE control code\n'
        '    at all (e.g. still the factory blink sketch, or nothing flashed)\n'
        'If you saw clean, repeating, sensible-looking bytes at one baud rate\n'
        'but garbage at others, that baud rate is very likely correct.'
    )


if __name__ == '__main__':
    main()
