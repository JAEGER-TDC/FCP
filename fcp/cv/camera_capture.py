"""
camera_capture.py — Shared, crash-isolated live camera capture.

Used by both the CV engine (DNE-mounted camera, annotated/processed by
TensorRT) and the Overwatch view (laptop-mounted field camera, raw
passthrough only, no CV). Runs the actual cv2.VideoCapture in an isolated
subprocess so a libjpeg crash from corrupted MJPG data (common over a USB
extender / WSL2 usbipd link) kills only the capture worker, never the FCP
itself — the worker auto-restarts on the next frame cycle.

cam_device may be an int index (/dev/videoN) or a device path string,
including a stable /dev/v4l/by-id/... symlink — pass whichever uniquely
identifies the physical camera you mean, since plain indices can silently
swap between two cameras depending on attach order.
"""

import json
import os
import time
import threading
import ctypes as _ct
import multiprocessing as _mp

import numpy as np

# Remembers which (fourcc, w, h, fps) actually delivered frames for each
# camera, keyed by device identifier — so reconnecting the *same* physical
# camera tries the known-good format first instead of re-probing the whole
# candidate list (each failed candidate costs up to `timeout` seconds).
_FORMAT_CACHE_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'data', 'camera_format_cache.json')


def _load_format_cache() -> dict:
    try:
        with open(_FORMAT_CACHE_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_format_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_FORMAT_CACHE_PATH), exist_ok=True)
        with open(_FORMAT_CACHE_PATH, 'w') as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass

# MJPG first: proven to negotiate frames on the field camera/USB extender
# combo in this project. YUYV is tried as a fallback for cameras that don't
# do MJPG; (None, ...) lets the driver pick as a last resort.
DEFAULT_CANDIDATES = [
    ('MJPG', 640, 480, 30),
    ('MJPG', 640, 480, 15),
    ('MJPG', 320, 240, 30),
    ('YUYV', 640, 480, 30),
    ('YUYV', 640, 480, 15),
    ('YUYV', 320, 240, 30),
    (None,   640, 480, 15),
]


def _camera_worker_proc(cam_device, fourcc_str, req_w, req_h, fps,
                        shared_arr, arr_shape, frame_count,
                        cap_props, stop_flag):
    """
    Isolated subprocess: opens the camera and writes frames into shared memory.
    libjpeg SIGSEGV / SIGABRT from corrupted MJPG data crash only this child;
    the parent FCP process is completely unaffected.
    """
    # libjpeg writes "Corrupt JPEG data: premature end of data segment" straight
    # to fd 2 from C — expected over a USB extender/usbipd link, not a Python
    # warning, so silencing requires an OS-level fd redirect, not logging config.
    _devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(_devnull, 2)

    import cv2
    import numpy as np

    buf = np.frombuffer(shared_arr.get_obj(), dtype=np.uint8).reshape(arr_shape)

    cap = cv2.VideoCapture(cam_device, cv2.CAP_V4L2)
    if fourcc_str:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc_str))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,      req_w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,     req_h)
    cap.set(cv2.CAP_PROP_FPS,              fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE,       4)
    cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)

    # Report actual negotiated properties back to parent via shared array.
    cap_props[0] = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    cap_props[1] = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    cap_props[2] = cap.get(cv2.CAP_PROP_FPS) or fps
    cap_props[3] = cap.get(cv2.CAP_PROP_SAR_NUM)
    cap_props[4] = cap.get(cv2.CAP_PROP_SAR_DEN)

    while not stop_flag.value:
        try:
            ret, frame = cap.read()
        except Exception:
            continue
        if not ret or frame is None or frame.size == 0:
            continue
        if frame.shape == arr_shape:
            np.copyto(buf, frame)
            with frame_count.get_lock():
                frame_count.value += 1

    cap.release()


class LiveCapture:
    """
    Camera capture using an isolated subprocess for crash safety.

    libjpeg aborts (SIGSEGV / SIGABRT) from corrupted MJPG data kill only the
    worker subprocess; the parent FCP process survives and the worker restarts
    automatically on the next frame cycle.
    """

    _CTX = _mp.get_context('spawn')  # safe with Qt's multi-threaded parent

    def __init__(self, cam_device, fourcc_str: str | None,
                 w: int, h: int, fps: int):
        self._cam_device = cam_device
        self._fourcc_str = fourcc_str
        self._req_w      = w
        self._req_h      = h
        self._req_fps    = fps
        self._shape      = (h, w, 3)

        self._frame: np.ndarray | None = None
        self._lock   = threading.Lock()
        self._ready  = threading.Event()
        self._stopped = False

        n = h * w * 3
        self._shared_arr  = self._CTX.Array(_ct.c_uint8,  n)
        self._frame_count = self._CTX.Value(_ct.c_uint64, 0)
        self._stop_flag   = self._CTX.Value(_ct.c_bool,   False)
        self._cap_props   = self._CTX.Array(_ct.c_double, 5)  # w,h,fps,sar_n,sar_d

        self._start_worker()
        self._mon = threading.Thread(target=self._monitor, daemon=True,
                                     name='LiveCapMon')
        self._mon.start()

    def _start_worker(self):
        self._proc = self._CTX.Process(
            target=_camera_worker_proc,
            args=(self._cam_device, self._fourcc_str,
                  self._req_w, self._req_h, self._req_fps,
                  self._shared_arr, self._shape,
                  self._frame_count, self._cap_props, self._stop_flag),
            daemon=True,
        )
        self._proc.start()

    def _monitor(self):
        buf  = np.frombuffer(self._shared_arr.get_obj(),
                             dtype=np.uint8).reshape(self._shape)
        last = 0
        while not self._stopped:
            if not self._proc.is_alive() and not self._stop_flag.value:
                print(f'[Camera] worker crashed (exit {self._proc.exitcode}), restarting...')
                self._start_worker()
            with self._frame_count.get_lock():
                cnt = self._frame_count.value
            if cnt != last:
                last  = cnt
                frame = buf.copy()
                with self._lock:
                    self._frame = frame
                self._ready.set()
            else:
                time.sleep(0.005)

    def read(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def wait_first(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    def get_props(self) -> tuple:
        """(act_w, act_h, fps, sar_num, sar_den) as reported by the subprocess."""
        return tuple(self._cap_props)

    def stop(self):
        self._stopped = True
        self._stop_flag.value = True
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=2.0)


def _resolve_device_path(cam_device) -> tuple:
    """Returns (cam_device_for_cv2, dev_path_to_check_exists)."""
    if isinstance(cam_device, str) and cam_device.isdigit():
        cam_device = int(cam_device)
    if isinstance(cam_device, int):
        return cam_device, f'/dev/video{cam_device}'
    return cam_device, cam_device   # string path (e.g. /dev/v4l/by-id/...)


def open_live_camera(cam_device, candidates: list | None = None,
                     timeout: float = 5.0, log_prefix: str = '[Camera]'):
    """Try each candidate format until frames actually arrive.

    cam_device: int index or device path string (by-id path recommended
    when more than one camera may be attached, since indices can silently
    swap between cameras depending on attach order).

    Returns (LiveCapture, None) on success, or (None, error_message) on
    failure — never raises.
    """
    cam_device, dev_path = _resolve_device_path(cam_device)
    if not os.path.exists(dev_path):
        return None, (f"{dev_path} not found — camera not attached. "
                      f"On WSL2: usbipd attach --wsl --busid <ID> in PowerShell (Admin).")

    cache_key = str(cam_device)
    cache = _load_format_cache()
    ordered = list(candidates or DEFAULT_CANDIDATES)
    cached = cache.get(cache_key)
    if cached:
        cached_tuple = (cached['fourcc'], cached['w'], cached['h'], cached['fps'])
        # Known-good format for this exact device, tried first — every other
        # candidate is a fallback only if the camera's behavior has changed.
        ordered = [cached_tuple] + [c for c in ordered if c != cached_tuple]

    for fourcc_str, w, h, fps in ordered:
        print(f'{log_prefix} trying {fourcc_str or "auto"} {w}x{h}@{fps}fps on {dev_path} ...')
        cap = LiveCapture(cam_device, fourcc_str, w, h, fps)
        if cap.wait_first(timeout=timeout):
            act_w, act_h, act_fps, _, _ = cap.get_props()
            act_w, act_h = int(act_w) or w, int(act_h) or h
            print(f'{log_prefix} camera OK: {fourcc_str or "auto"} {act_w}x{act_h} @{act_fps:.0f}fps')
            cache[cache_key] = {'fourcc': fourcc_str, 'w': w, 'h': h, 'fps': fps}
            _save_format_cache(cache)
            return cap, None
        print(f'{log_prefix} no frames — skipping')
        cap.stop()

    return None, ("Camera opened but no frames received — "
                  "check usbipd attach and /dev/video permissions")
