"""
cv_engine_sim.py — Simulated CV tracking engine.

Reads drone.mp4, runs a scripted state machine, and renders the full
cv.py HUD (via cv_draw) onto each frame.  Implements the same interface
as the future real TRT engine so no other code needs to change when
hardware is available.

State cycle (loops indefinitely):
    SEARCHING (2 s) → LOCKED (5 s) → DARK LOCK (3 s) → PREDICTING (2 s) → …

Centroid follows a compound sinusoidal path so the crosshair moves
realistically across the frame even during non-LOCKED states.
"""

import math
import queue
import threading
import time
from collections import deque

import cv2
import numpy as np

from cv.cv_draw import Config, _draw_hud, _draw_trail, _draw_zoom_inset, compute_laser_pos


_STATE_CYCLE = ["SEARCHING", "LOCKED", "DARK LOCK", "PREDICTING"]

_STATE_DURATIONS = {
    "SEARCHING":  2.0,
    "LOCKED":     5.0,
    "DARK LOCK":  3.0,
    "PREDICTING": 2.0,
}

_STATE_COLORS = {
    "LOCKED":     (0, 255, 0),
    "DARK LOCK":  (0, 140, 255),
    "PREDICTING": (0, 165, 255),
    "SEARCHING":  (0, 80,  255),
}


class CVEngineSimulator:
    """
    Simulated CV engine.  Drop-in replacement for the future TRT-based engine.

    Usage:
        engine = CVEngineSimulator(video_path)
        engine.start()
        frame = engine.read_frame()   # returns annotated BGR ndarray or None
        meta  = engine.get_metadata() # {state, confidence, cx, cy, frame_w, frame_h}
        engine.stop()
    """

    def __init__(self, video_path: str, cfg: Config | None = None):
        self._video_path  = video_path
        self._cfg         = cfg or Config()
        self._frame_queue: queue.Queue = queue.Queue(maxsize=2)
        self._meta: dict = {
            "state": "SEARCHING", "confidence": 0.0,
            "cx": 0, "cy": 0, "frame_w": 0, "frame_h": 0,
            "gimbal_err_px": 0.0, "on_target": False,
            "bbox_w": 0, "bbox_h": 0,
        }
        self._meta_lock          = threading.Lock()
        self._stop_evt           = threading.Event()
        self._reset_tracking_evt = threading.Event()
        self._restart_video_evt  = threading.Event()
        self._screenshot_request = threading.Event()
        self._paused             = False
        self._last_frame: np.ndarray | None = None
        self._thread: threading.Thread | None = None

    # ── Public interface ──────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="CVEngineSimulator")
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def read_frame(self) -> np.ndarray | None:
        """Return the latest annotated BGR frame, or None if not yet ready."""
        try:
            return self._frame_queue.get_nowait()
        except queue.Empty:
            return None

    def get_metadata(self) -> dict:
        """Return a snapshot of the current tracking state."""
        with self._meta_lock:
            return dict(self._meta)

    def pause_toggle(self) -> bool:
        self._paused = not self._paused
        return self._paused

    def is_paused(self) -> bool:
        return self._paused

    def reset_tracking(self) -> None:
        self._reset_tracking_evt.set()

    def take_screenshot(self) -> None:
        self._screenshot_request.set()

    def restart_video(self) -> None:
        self._restart_video_evt.set()

    def get_raw_frame(self) -> np.ndarray | None:
        """The simulator doesn't separate raw from annotated; return last frame."""
        return self._last_frame

    # ── Background thread ─────────────────────────────────────────

    def _run(self) -> None:
        cap = cv2.VideoCapture(self._video_path)
        if not cap.isOpened():
            print(f"CVEngineSimulator: cannot open {self._video_path}")
            return

        fps_src   = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_dt  = 1.0 / fps_src

        # State machine
        state_idx     = 0
        status        = _STATE_CYCLE[state_idx]
        color         = _STATE_COLORS[status]
        state_elapsed = 0.0

        # Sinusoid phase for centroid path
        phase     = 0.0

        # Trail (deque mirrors cv.py's trail deque)
        trail: deque = deque(maxlen=self._cfg.TRAIL_LENGTH)

        # HUD counters
        frame_num   = 0
        lost_frames = 0
        prev_cx = prev_cy = 0
        avg_fps = fps_src

        prev_t = time.perf_counter()

        while not self._stop_evt.is_set():
            if self._paused:
                self._stop_evt.wait(0.05)
                continue

            if self._reset_tracking_evt.is_set():
                self._reset_tracking_evt.clear()
                state_idx = 0
                status = _STATE_CYCLE[state_idx]
                color  = _STATE_COLORS[status]
                state_elapsed = 0.0
                trail.clear()

            if self._restart_video_evt.is_set():
                self._restart_video_evt.clear()
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                state_idx = 0
                status = _STATE_CYCLE[state_idx]
                color  = _STATE_COLORS[status]
                state_elapsed = 0.0
                trail.clear()
                frame_num = 0

            t0 = time.perf_counter()
            dt = max(t0 - prev_t, 1e-6)
            prev_t = t0

            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                cap.read()  # discard first frame after rewind to avoid duplicate
                continue

            frame_num += 1
            h, w = frame.shape[:2]

            # ── Advance state machine ─────────────────────────────
            state_elapsed += dt
            if state_elapsed >= _STATE_DURATIONS[status]:
                state_elapsed = 0.0
                state_idx = (state_idx + 1) % len(_STATE_CYCLE)
                status    = _STATE_CYCLE[state_idx]
                color     = _STATE_COLORS[status]

            # ── Advance centroid sinusoid ─────────────────────────
            phase += dt * 0.4   # ~16-second full horizontal sweep
            cx = int((0.5 + 0.35 * math.sin(phase)) * w)
            cy = int((0.35 + 0.15 * math.sin(phase * 0.7 + 1.0)) * h)

            # Velocity (px/frame, approximate)
            vx = (cx - prev_cx) / max(dt, 1e-6)
            vy = (cy - prev_cy) / max(dt, 1e-6)
            prev_cx, prev_cy = cx, cy

            # Confidence: non-zero only during LOCKED
            conf = 0.0
            if status == "LOCKED":
                conf = round(0.80 + 0.18 * abs(math.sin(phase * 3)), 4)
                conf = min(conf, 1.0)

            lost_frames = 0 if status in ("LOCKED", "DARK LOCK") else lost_frames + 1

            # ── Render HUD ────────────────────────────────────────
            show = frame.copy()

            if status in ("LOCKED", "DARK LOCK"):
                trail.append((cx, cy))
            elif status == "SEARCHING":
                trail.clear()

            laser_x, laser_y = compute_laser_pos(w, h, self._cfg)
            gimbal_err = math.sqrt((cx - laser_x) ** 2 + (cy - laser_y) ** 2)
            on_target  = (status == "LOCKED") and (gimbal_err < self._cfg.ENGAGE_RADIUS_PX)

            with self._meta_lock:
                self._meta.update(
                    state=status, confidence=conf,
                    cx=cx, cy=cy, frame_w=w, frame_h=h,
                    gimbal_err_px=round(gimbal_err, 1),
                    on_target=on_target,
                )

            if self._cfg.SHOW_TRAIL:
                _draw_trail(show, trail, color)

            frame_ms = (time.perf_counter() - t0) * 1000
            avg_fps  = 0.05 * (1000.0 / max(frame_ms, 0.1)) + 0.95 * avg_fps

            _draw_hud(
                show, cx, cy, laser_x, laser_y,
                status, color,
                fps=avg_fps, peak_ms=frame_ms, conf=conf,
                lost_frames=lost_frames, frame_num=frame_num,
                vx=vx, vy=vy,
                dark_blobs=[], sky_ref=180,
                arduino_ok=False, cfg=self._cfg,
            )

            if self._cfg.SHOW_ZOOM_INSET and status in ("LOCKED", "DARK LOCK"):
                _draw_zoom_inset(show, frame, cx, cy, self._cfg, color)

            self._last_frame = show

            if self._screenshot_request.is_set():
                self._screenshot_request.clear()
                import time as _t
                fname = f"cv_shot_{int(_t.time())}.png"
                cv2.imwrite(fname, show)
                print(f"[CV] Screenshot saved: {fname}")

            # ── Push to display queue ─────────────────────────────
            try:
                self._frame_queue.put_nowait(show)
            except queue.Full:
                try:
                    self._frame_queue.get_nowait()   # drop oldest
                except queue.Empty:
                    pass
                self._frame_queue.put_nowait(show)

            # ── Pace to source FPS ────────────────────────────────
            elapsed = time.perf_counter() - t0
            wait    = frame_dt - elapsed
            if wait > 0:
                time.sleep(wait)

        cap.release()
