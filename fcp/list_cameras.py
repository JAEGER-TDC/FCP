"""
list_cameras.py — Identify cameras by stable device path, not bare index.

With two USB cameras attached (one on the DNE, one for the laptop-mounted
Overwatch view), /dev/video0 vs /dev/video1 can silently swap between the
two physical cameras depending on attach order — the same problem solved
for serial ports via /dev/serial/by-id/. This is the video equivalent.

Run from the repo root:
    poetry run python fcp/list_cameras.py
"""

import glob
import os
import re
import subprocess


def _read_sys(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _udevadm_property(dev_path: str, key: str) -> str | None:
    try:
        out = subprocess.run(
            ['udevadm', 'info', '-q', 'property', '-n', dev_path],
            capture_output=True, text=True, timeout=2,
        ).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    m = re.search(rf'^{re.escape(key)}=(.*)$', out, re.MULTILINE)
    return m.group(1) if m else None


def main():
    video_devs = sorted(
        glob.glob('/dev/video*'),
        key=lambda p: int(re.sub(r'\D', '', p) or 0),
    )

    print('=== Video devices currently visible to this machine ===')
    if not video_devs:
        print('  (none found — is a camera attached? On WSL2, check '
              '`usbipd attach --wsl --busid <ID>` succeeded on the Windows side.)')
    for dev in video_devs:
        idx = re.sub(r'\D', '', dev)
        name = _read_sys(f'/sys/class/video4linux/video{idx}/name') or '?'
        vendor  = _udevadm_property(dev, 'ID_VENDOR_FROM_DATABASE') or _udevadm_property(dev, 'ID_VENDOR') or '?'
        model   = _udevadm_property(dev, 'ID_MODEL_FROM_DATABASE')  or _udevadm_property(dev, 'ID_MODEL')  or '?'
        serial  = _udevadm_property(dev, 'ID_SERIAL_SHORT') or '?'
        print(f'  {dev}')
        print(f'      name        : {name}')
        print(f'      vendor      : {vendor}')
        print(f'      model       : {model}')
        print(f'      serial      : {serial}')

    by_id_dir = '/dev/v4l/by-id'
    by_id_links = sorted(glob.glob(os.path.join(by_id_dir, '*'))) if os.path.isdir(by_id_dir) else []
    print(f'\n=== Stable by-id paths ({by_id_dir}) — prefer these in config.ini ===')
    if not by_id_links:
        print('  (none — only appears once at least one camera is attached)')
    for link in by_id_links:
        print(f'  {link}\n      -> {os.path.realpath(link)}')

    print(
        '\nIf two cameras show similar names, unplug one at a time and re-run\n'
        'this script to see which by-id entry disappears — that tells you\n'
        'definitively which physical camera is which.\n'
        '\nSet the DNE-mounted camera in the CV launch dialog (camera index),\n'
        'and the Overwatch (laptop) camera via config.ini:\n'
        '  [overwatch.camera]\n'
        '  device = /dev/v4l/by-id/usb-...-index0\n'
    )


if __name__ == '__main__':
    main()
