"""
CVEngine — real TensorRT-based CV engine for the JAEGER FCP.

Drop-in replacement for CVEngineSimulator. Same public interface:
    start()        — launch background tracking thread
    stop()         — stop and join thread
    read_frame()   — non-blocking; returns annotated BGR ndarray or None
    get_metadata() — thread-safe dict: state/confidence/centroid/gimbal_err
    get_error()    — returns error string if TRT failed to load, else None

NOTE: cv.cv imports (tensorrt, cupy) are deferred into _run() so this module
can be imported on any machine regardless of GPU/TRT availability.
"""

import os
import time
import queue
import threading
from collections import deque

import cv2
import numpy as np


class CVEngine:
    """Real TensorRT CV engine — same interface as CVEngineSimulator."""

    def __init__(self, video_path: str, cfg=None):
        self._video_path    = video_path
        self._cfg           = cfg          # None → default Config() created in _run()
        self._frame_queue   = queue.Queue(maxsize=2)
        self._metadata: dict = {
            "state": "SEARCHING", "confidence": 0.0,
            "cx": 0, "cy": 0,
            "frame_w": 0, "frame_h": 0,
            "gimbal_err_px": 0.0, "on_target": False,
        }
        self._lock               = threading.Lock()
        self._stop_event         = threading.Event()
        self._reset_filters      = threading.Event()
        self._reset_tracking     = threading.Event()
        self._restart_video      = threading.Event()
        self._screenshot_request = threading.Event()
        self._paused             = False
        self._last_frame: np.ndarray | None = None
        self._thread: threading.Thread | None = None
        self._error: str | None = None

    # ── Public API ────────────────────────────────────────────────────────

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def read_frame(self):
        try:
            return self._frame_queue.get_nowait()
        except queue.Empty:
            return None

    def get_metadata(self) -> dict:
        with self._lock:
            return dict(self._metadata)

    def get_error(self) -> str | None:
        return self._error

    def update_config(self, attr: str, value) -> None:
        """Mutate a Config field live — the tracking loop picks it up next frame.
        OneEuroFilter params also trigger a filter reset so smoothing changes apply."""
        if self._cfg is None:
            return
        setattr(self._cfg, attr, value)
        if attr in ('oef_min_cutoff', 'oef_beta'):
            self._reset_filters.set()

    def pause_toggle(self) -> bool:
        """Toggle pause/resume. Returns True if now paused."""
        self._paused = not self._paused
        return self._paused

    def is_paused(self) -> bool:
        return self._paused

    def reset_tracking(self) -> None:
        """Signal the loop to reset Kalman filter and all tracking state."""
        self._reset_tracking.set()

    def take_screenshot(self) -> None:
        """Save the last rendered frame to disk."""
        self._screenshot_request.set()

    def restart_video(self) -> None:
        """Rewind video to start and reset tracking (no-op in camera mode)."""
        self._restart_video.set()

    # ── Background thread ─────────────────────────────────────────────────

    def _run(self):
        # Inject the CV project venv so TRT/cupy are findable even from the Poetry venv
        import sys
        _CV_SITE = "/home/lockheed/FCP_CV_Project/venv/lib/python3.12/site-packages"
        if _CV_SITE not in sys.path:
            sys.path.insert(0, _CV_SITE)

        # Deferred import — keeps this module importable even without TRT/cupy
        try:
            from cv.cv import (
                Config, TRTInference, KalmanTracker, OneEuroFilter, FrameReader,
                dark_pixel_search, _draw_trail, _draw_zoom_inset, _draw_hud,
                compute_laser_pos, compute_gimbal_error, refine_to_dark_centroid,
                _sky_brightness,
            )
        except ImportError as exc:
            self._error = str(exc)
            return

        # Resolve config now that Config class is available
        if self._cfg is None:
            self._cfg = Config()
        cfg  = self._cfg
        base = os.path.dirname(os.path.abspath(__file__))

        try:
            model = TRTInference(os.path.join(base, cfg.engine_path), cfg.input_size)
        except Exception as exc:
            self._error = str(exc)
            return

        is_live = getattr(cfg, 'USE_LIVE_CAMERA', False)
        if is_live:
            cam_idx = getattr(cfg, 'CAMERA_INDEX', 0)
            cap = cv2.VideoCapture(cam_idx)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                self._error = f"Cannot open camera index {cam_idx}"
                return
        else:
            cap = cv2.VideoCapture(self._video_path)
            if not cap.isOpened():
                self._error = f"Cannot open video: {self._video_path}"
                return

        cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
        fps_src   = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_dt  = 1.0 / fps_src
        w_cap     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h_cap     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        sar_num = cap.get(cv2.CAP_PROP_SAR_NUM)
        sar_den = cap.get(cv2.CAP_PROP_SAR_DEN)
        if sar_num > 0 and sar_den > 0 and abs(sar_num / sar_den - 1.0) > 0.02:
            display_w = max(1, int(w_cap * sar_num / sar_den))
            display_h = h_cap
        else:
            display_w, display_h = w_cap, h_cap
        needs_resize = (display_w != w_cap or display_h != h_cap)

        reader   = FrameReader(cap)
        filter_x = OneEuroFilter(cfg.oef_min_cutoff, cfg.oef_beta)
        filter_y = OneEuroFilter(cfg.oef_min_cutoff, cfg.oef_beta)
        kalman   = KalmanTracker()
        trail    = deque(maxlen=cfg.TRAIL_LENGTH)

        avg_fps      = fps_src
        prev_time    = time.perf_counter()
        lost_frames  = 0
        last_conf    = 0.0
        frame_num    = 0
        cx = cy      = 0
        frame_times: list[float] = []
        dark_no_conf = 0
        dark_grace   = 999
        status       = "SEARCHING"
        color        = (0, 80, 255)

        while not self._stop_event.is_set():
            # Pause support — hold last frame on screen, drain reader to prevent stale buffer
            if self._paused:
                self._stop_event.wait(0.05)
                continue

            # Manual tracking reset (keyboard shortcut r)
            if self._reset_tracking.is_set():
                self._reset_tracking.clear()
                filter_x.reset(); filter_y.reset(); kalman.reset()
                trail.clear()
                dark_no_conf = 0; dark_grace = 999; lost_frames = 0
                cx = cy = 0
                status, color = "SEARCHING", (0, 80, 255)

            # Video restart (keyboard shortcut v)
            if self._restart_video.is_set():
                self._restart_video.clear()
                if not is_live:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    reader.stop()
                    reader = FrameReader(cap)
                filter_x.reset(); filter_y.reset(); kalman.reset()
                trail.clear()
                dark_no_conf = 0; dark_grace = 999; lost_frames = 0
                cx = cy = 0; frame_num = 0
                status, color = "SEARCHING", (0, 80, 255)

            frame = reader.read()
            if frame is None:
                if is_live:
                    break
                # Video ended — rewind and restart
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                reader.stop()
                reader = FrameReader(cap)
                filter_x.reset(); filter_y.reset(); kalman.reset()
                trail.clear()
                dark_no_conf = 0; dark_grace = 999; lost_frames = 0
                status, color = "SEARCHING", (0, 80, 255)
                frame_num = 0
                continue

            # Rebuild OEF if smoothing params were updated via update_config()
            if self._reset_filters.is_set():
                self._reset_filters.clear()
                filter_x = OneEuroFilter(self._cfg.oef_min_cutoff, self._cfg.oef_beta)
                filter_y = OneEuroFilter(self._cfg.oef_min_cutoff, self._cfg.oef_beta)

            t1        = time.perf_counter()
            dt        = max(t1 - prev_time, 1e-6)
            prev_time = t1
            h, w      = frame.shape[:2]
            frame_num += 1

            gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sky_ref = _sky_brightness(gray)

            raw       = model.run(frame)[0]
            confs     = raw[4, :]
            best_idx  = int(np.argmax(confs))
            best_conf = float(confs[best_idx])
            threshold = cfg.CONF_HOLD if kalman.initialized else cfg.CONF_ACQUIRE

            hint_xy = None
            if cfg.CONF_HINT > 0 and cfg.CONF_HINT <= best_conf < threshold:
                hint_xy = (raw[0, best_idx] * (w / cfg.input_size),
                           raw[1, best_idx] * (h / cfg.input_size))

            dark_blobs: list = []
            dark_found       = False
            dark_cx = dark_cy = 0
            if cfg.DARK_SEARCH_ENABLED and best_conf < threshold:
                dark_cx, dark_cy, dark_found, dark_blobs = dark_pixel_search(
                    gray, kalman, cfg, w, h, sky_ref,
                    hint_xy=hint_xy, frame_bgr=frame)

            if best_conf >= threshold:
                rx     = raw[0, best_idx] * (w / cfg.input_size)
                ry     = raw[1, best_idx] * (h / cfg.input_size)
                bw_raw = raw[2, best_idx] * (w / cfg.input_size)
                bh_raw = raw[3, best_idx] * (h / cfg.input_size)
                rx, ry = refine_to_dark_centroid(gray, rx, ry, bw_raw, bh_raw)
                cx     = int(filter_x.apply(rx, dt))
                cy     = int(filter_y.apply(ry, dt))
                kalman.update(cx, cy, dt)
                lost_frames = 0; last_conf = best_conf
                dark_no_conf = 0; dark_grace = 999
                status, color = "LOCKED", (0, 255, 0)

            elif dark_found:
                cx = int(filter_x.apply(float(dark_cx), dt))
                cy = int(filter_y.apply(float(dark_cy), dt))
                kalman.update(cx, cy, dt)
                lost_frames = 0; last_conf = 0.0
                dark_grace = 0; dark_no_conf = 0
                status, color = "DARK LOCK", (0, 140, 255)

            elif dark_grace < cfg.DARK_GRACE_FRAMES and kalman.initialized:
                dark_grace += 1; dark_no_conf += 1; lost_frames = 0
                px, py = kalman.predict(dt)
                if px is not None:
                    cx, cy = int(px), int(py)
                if dark_no_conf >= cfg.DARK_LOCK_CONF_TIMEOUT:
                    dark_no_conf = 0; dark_grace = 999
                    filter_x.reset(); filter_y.reset(); kalman.reset()
                    status, color = "SEARCHING", (0, 80, 255)
                else:
                    status, color = "DARK LOCK", (0, 140, 255)

            elif cfg.KALMAN_ENABLED and kalman.initialized and lost_frames < cfg.max_lost_frames:
                px, py = kalman.predict(dt)
                if px is not None:
                    cx, cy = int(px), int(py)
                lost_frames += 1
                status, color = "PREDICTING", (0, 165, 255)

            else:
                filter_x.reset(); filter_y.reset(); kalman.reset()
                dark_no_conf = 0; dark_grace = 999
                status, color = "SEARCHING", (0, 80, 255)

            vx, vy   = kalman.velocity()
            frame_ms = (time.perf_counter() - t1) * 1000
            avg_fps  = 0.05 * (1000.0 / max(frame_ms, 0.1)) + 0.95 * avg_fps
            frame_times.append(frame_ms)
            if len(frame_times) > 60:
                frame_times.pop(0)
            peak_ms = max(frame_times)

            show = cv2.resize(frame, (display_w, display_h)) if needs_resize else frame.copy()
            sx   = display_w / w
            sy   = display_h / h
            scx  = max(0, min(int(cx * sx), display_w - 1))
            scy  = max(0, min(int(cy * sy), display_h - 1))
            laser_x, laser_y = compute_laser_pos(display_w, display_h, cfg)
            blobs_show = [(int(bx * sx), int(by * sy), a) for bx, by, a in dark_blobs]

            if status in ("LOCKED", "DARK LOCK"):
                trail.append((scx, scy))
            elif status == "SEARCHING":
                trail.clear()

            if cfg.SHOW_TRAIL:
                _draw_trail(show, trail, color)

            _draw_hud(show, scx, scy, laser_x, laser_y,
                      status, color, avg_fps, peak_ms, last_conf,
                      lost_frames, frame_num, vx, vy, blobs_show, sky_ref,
                      False, cfg)

            if cfg.SHOW_ZOOM_INSET and status in ("LOCKED", "DARK LOCK"):
                _draw_zoom_inset(show, frame, cx, cy, cfg, color)

            # Metadata in frame-space coords (matches CVEngineSimulator convention)
            laser_fx = w // 2 + cfg.LASER_OFFSET_X
            laser_fy = h // 2 + cfg.LASER_OFFSET_Y
            _, _, err = compute_gimbal_error(cx, cy, laser_fx, laser_fy)
            on_target = status in ("LOCKED", "DARK LOCK") and err < cfg.ENGAGE_RADIUS_PX
            with self._lock:
                self._metadata = {
                    "state": status, "confidence": last_conf,
                    "cx": cx, "cy": cy,
                    "frame_w": w, "frame_h": h,
                    "gimbal_err_px": err, "on_target": on_target,
                }

            self._last_frame = show

            # Screenshot (keyboard shortcut s)
            if self._screenshot_request.is_set():
                self._screenshot_request.clear()
                fname = f"cv_shot_{int(time.time())}.png"
                cv2.imwrite(fname, show)
                print(f"[CV] Screenshot saved: {fname}")

            try:
                self._frame_queue.put_nowait(show)
            except queue.Full:
                try:
                    self._frame_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._frame_queue.put_nowait(show)
                except queue.Full:
                    pass

            elapsed = time.perf_counter() - t1
            sleep_s = frame_dt - elapsed - 0.001
            if sleep_s > 0:
                self._stop_event.wait(sleep_s)

        reader.stop()
        cap.release()
