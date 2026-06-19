"""
drone_tracking_GPU_v10.py  —  

Tracking modes (automatic, in priority order)
----------------------------------------------
  LOCKED     TensorRT GPU model detected the drone with high confidence.
             Centroid is refined to the weighted center-of-mass of the
             darkest pixels inside the detection box.
  DARK LOCK  CV model lost it; dark-pixel search took over.
             Keeps only blobs that do NOT touch the frame bottom/sides
             (floating = drone, ground-connected = everything else).
  PREDICTING CV and dark search both failed; Kalman filter coasts on
             last known velocity.  Short window (max_lost_frames).
  SEARCHING  Full reset — scanning the whole frame for a dark blob.

Keyboard shortcuts
------------------
  SPACE  pause / resume
  r      reset tracking
  s      screenshot
  q      quit
"""

import os
import time
import threading
import queue
from collections import deque

import cv2
import numpy as np
import tensorrt as trt
import cupy as cp
from dataclasses import dataclass

try:
    import serial as _serial
    _SERIAL_AVAIL = True
except ImportError:
    _SERIAL_AVAIL = False

# This silences the Qt Font warnings specifically
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.fonts=false"
# This tells OpenCV to use the simpler built-in header if the fancy one fails
os.environ["QT_QPA_PLATFORM"] = "xcb"

# ══════════════════════════════════════════════════════════════════
#  CONFIGURATION  — every tunable in one place
# ══════════════════════════════════════════════════════════════════
@dataclass
class Config:

    # ── Source ────────────────────────────────────────────────────
    USE_LIVE_CAMERA:    bool  = False       # True = webcam, False = video file
    CAMERA_INDEX:       int   = 0           # webcam index (USE_LIVE_CAMERA=True)
    video_path:         str   = "RAT-CV-1.mp4"
    save_path:          str   = ".mp4"
    SAVE_OUTPUT:        bool  = False       # write annotated video to save_path

    # ── TensorRT model ────────────────────────────────────────────
    engine_path:        str   = "best.engine"
    input_size:         int   = 320         # must match engine input (px)

    # ── CV confidence thresholds ──────────────────────────────────
    # ↑ CONF_ACQUIRE  harder to lock on  →  fewer false locks
    # ↓ CONF_ACQUIRE  easier to lock on  →  picks up drone faster
    # ↑ CONF_HOLD     drops lock sooner  →  faster to switch to dark search
    # CONF_HINT       if model has faint signal, seeds the dark search window
    CONF_ACQUIRE:       float = 0.25        # confidence needed to acquire lock  (0.15–0.35)
    CONF_HOLD:          float = 0.10        # confidence needed to stay locked   (0.05–0.15)
    CONF_HINT:          float = 0.05        # faint hint threshold for dark seed (0.03–0.08)

    # ── Kalman coast (PREDICTING mode) ────────────────────────────
    # How many frames to coast on Kalman before giving up and resetting.
    # ↓ shorter  →  faster switch to full-frame SEARCHING (recommended for fast drones)
    # ↑ longer   →  smoother through brief occlusions, but guided search may drift
    KALMAN_ENABLED:     bool  = True
    max_lost_frames:    int   = 100          # frames before full reset  (15–60)

    # ── Dark-pixel search ─────────────────────────────────────────
    # Detects the drone by finding dark blobs that do NOT touch the
    # bottom, left, or right frame edge (floating = drone in sky).
    # Sky brightness is sampled live so thresholds adapt to lighting.
    #
    # DARK_PIXEL_RATIO  how dark a blob must be vs measured sky brightness
    #   ↓ lower  →  only very dark blobs qualify  →  misses gray drone
    #   ↑ higher →  allows lighter blobs          →  more false positives
    #
    # DARK_MIN_AREA     smallest blob accepted (full-res px²)
    #   ↓ lower  →  detects farther / smaller drone  →  more noise
    #   ↑ higher →  ignores small blobs              →  misses distant drone
    #   Guide: ~30 ft ≈ 500–3000 px², ~100 ft ≈ 30–150 px²
    #
    # DARK_MAX_AREA     largest blob accepted — prevents locking on clouds
    #   Raise if a very close large drone is being skipped.
    #
    # DARK_SEARCH_RADIUS  when guided (Kalman/hint), only search within
    #   this many px of the predicted position. Raise for fast drones.
    DARK_SEARCH_ENABLED:  bool  = True
    DARK_PIXEL_RATIO:     float = 0.55      # blob < sky * ratio         (0.45–0.65)
    DARK_MIN_AREA:        int   = 150       # min blob area full-res px² — raise to kill small pole hardware
    DARK_MAX_AREA:        int   = 20000     # max blob area full-res px²
    DARK_SEARCH_RADIUS:   int   = 300       # guided search window radius (150–400)
    # Sky-color ring check: requires ring pixels to have B > R (sky is blue).
    # Very reliable on clear/partly-cloudy days for rejecting gray metal poles.
    # Disable on fully overcast days where sky is white (B ≈ R).
    DARK_COLOR_CHECK:     bool  = True      # blue-sky color ring filter

    # ── Dark lock hysteresis ──────────────────────────────────────
    # How many consecutive frames dark search can MISS before we drop
    # to PREDICTING.  During these grace frames the last Kalman position
    # is held and the status stays "DARK LOCK" — stops flickering when
    # the drone blob briefly vanishes (cloud, motion blur, etc.).
    # ↑ higher  →  steadier lock through brief misses (8–15)
    # ↓ lower   →  faster reaction when drone truly disappears (3–6)
    DARK_GRACE_FRAMES:    int   = 10        # frames to hold dark lock on miss (5–15)

    # ── False-lock guard ──────────────────────────────────────────
    # In DARK LOCK, if the CV model gives no signal for this many frames,
    # assume we locked onto a background object and reset.
    # ↓ lower  →  releases false locks faster  →  may drop real lock on occlusion
    # ↑ higher →  tolerates longer occlusions  →  holds false lock longer
    DARK_LOCK_CONF_TIMEOUT: int = 20        # frames before false-lock release (15–45)

    # ── Laser / Gimbal physical offset ───────────────────────────
    # If the laser is not perfectly centred on the camera frame,
    # dial these in to align the crosshair with the actual beam.
    # Positive X = laser is to the RIGHT of frame centre.
    # Positive Y = laser is BELOW frame centre.
    LASER_OFFSET_X:     int   = 0           # px right of centre
    LASER_OFFSET_Y:     int   = 0           # px below centre

    # ── Position smoothing (One-Euro adaptive low-pass filter) ────
    # ↓ oef_min_cutoff  →  smoother path, more lag at low speed
    # ↑ oef_beta        →  reduces lag when drone moves fast
    oef_min_cutoff:     float = 0.05        # base smoothing  (0.03–0.10)
    oef_beta:           float = 0.002       # speed-adaptive term (0.001–0.005)

    # ── Display ───────────────────────────────────────────────────
    MAX_DISPLAY_W:      int   = 1728        # max window width  (~90% of 1920)
    MAX_DISPLAY_H:      int   = 972         # max window height (~90% of 1080)
    REALTIME_PLAYBACK:  bool  = True        # pace video to source FPS (file mode)

    # ── Arduino / Gimbal serial output ───────────────────────────
    # Sends "G<pan>,<tilt>,<locked>\n" to the Arduino each frame.
    # pan  = drone_x − laser_x  (+ = drone right of laser → pan right)
    # tilt = drone_y − laser_y  (+ = drone below laser  → tilt down)
    # locked = 1 while LOCKED or DARK LOCK, else 0
    ARDUINO_ENABLED:    bool  = False
    ARDUINO_PORT:       str   = "COM3"
    ARDUINO_BAUD:       int   = 115200
    ARDUINO_HZ:         int   = 30          # max serial send rate (Hz)

    # ── Engagement threshold ──────────────────────────────────────
    # "LASER ON TARGET" fires when gimbal error is below this (display px).
    # ↓ stricter  →  must be more precisely aimed before trigger
    # ↑ looser    →  triggers sooner but laser may not be centred
    ENGAGE_RADIUS_PX:   int   = 40          # display px  (20–80)

    # ── HUD overlay toggles ───────────────────────────────────────
    SHOW_HUD_PANEL:     bool  = True        # text info panel (top-left)
    SHOW_FPS:           bool  = True
    SHOW_CROSSHAIR:     bool  = True        # crosshair on drone
    SHOW_LOCK_RING:     bool  = True        # ring around drone when LOCKED
    SHOW_LASER_CENTER:  bool  = True        # diamond at laser aim point
    SHOW_OFFSET_LINE:   bool  = True        # dashed line laser→drone
    SHOW_GIMBAL_ERROR:  bool  = True        # pan/tilt error in HUD panel
    SHOW_DARK_BLOBS:    bool  = True        # blue dots on dark search candidates

    # ── Visual extras ─────────────────────────────────────────────
    SHOW_TRAIL:         bool  = True        # fading position history dots
    TRAIL_LENGTH:       int   = 60          # frames of trail history
    SHOW_ZOOM_INSET:    bool  = True        # magnified patch (bottom-right)
    ZOOM_INSET_SIZE:    int   = 220         # inset display size px (square)
    ZOOM_MAGNIFY:       int   = 4           # zoom magnification factor
    SHOW_VELOCITY_ARROW: bool = True        # arrow showing predicted heading


# ══════════════════════════════════════════════════════════════════
#  THREADED FRAME READER
# ══════════════════════════════════════════════════════════════════
_READER_END = object()

class FrameReader:
    def __init__(self, cap: cv2.VideoCapture, maxsize: int = 4):
        self._cap  = cap
        self._q    = queue.Queue(maxsize=maxsize)
        self._stop = threading.Event()
        self._t    = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        while not self._stop.is_set():
            if self._q.full():
                time.sleep(0.001)
                continue
            ret, frame = self._cap.read()
            if not ret:
                self._q.put(_READER_END)
                return
            self._q.put(frame)

    def read(self):
        while True:
            try:
                item = self._q.get(timeout=0.05)
                return None if item is _READER_END else item
            except queue.Empty:
                if not self._t.is_alive():
                    return None

    def stop(self):
        self._stop.set()
        self._t.join(timeout=1.0)


# ══════════════════════════════════════════════════════════════════
#  ONE-EURO FILTER
# ══════════════════════════════════════════════════════════════════
class OneEuroFilter:
    def __init__(self, min_cutoff=0.1, beta=0.0001, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta       = beta
        self.d_cutoff   = d_cutoff
        self.x_prev     = None
        self.dx_prev    = 0.0

    def _alpha(self, cutoff, dt):
        tau = 1.0 / (2 * np.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def apply(self, x, dt):
        if self.x_prev is None:
            self.x_prev = x
            return x
        if dt <= 0:
            return self.x_prev
        dx           = (x - self.x_prev) / dt
        edx          = self.dx_prev + self._alpha(self.d_cutoff, dt) * (dx - self.dx_prev)
        self.dx_prev = edx
        cutoff       = self.min_cutoff + self.beta * abs(edx)
        alpha        = self._alpha(cutoff, dt)
        x_hat        = self.x_prev + alpha * (x - self.x_prev)
        self.x_prev  = x_hat
        return x_hat

    def reset(self):
        self.x_prev  = None
        self.dx_prev = 0.0


# ══════════════════════════════════════════════════════════════════
#  KALMAN TRACKER
# ══════════════════════════════════════════════════════════════════
class KalmanTracker:
    def __init__(self):
        self.kf = cv2.KalmanFilter(4, 2)
        self.kf.transitionMatrix = np.array([
            [1, 0, 1, 0],
            [0, 1, 0, 1],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ], dtype=np.float32)
        self.kf.measurementMatrix    = np.array([[1,0,0,0],[0,1,0,0]], dtype=np.float32)
        self.kf.processNoiseCov      = np.eye(4, dtype=np.float32) * 1e-2
        self.kf.measurementNoiseCov  = np.eye(2, dtype=np.float32) * 1e-1
        self.kf.errorCovPost         = np.eye(4, dtype=np.float32)
        self.initialized = False

    def _set_dt(self, dt):
        self.kf.transitionMatrix[0, 2] = dt
        self.kf.transitionMatrix[1, 3] = dt

    def update(self, x, y, dt):
        self._set_dt(dt)
        if not self.initialized:
            self.kf.statePost = np.array([[x],[y],[0.],[0.]], dtype=np.float32)
            self.initialized  = True
        else:
            self.kf.predict()
            self.kf.correct(np.array([[x],[y]], dtype=np.float32))

    def predict(self, dt):
        if not self.initialized:
            return None, None
        self._set_dt(dt)
        p = self.kf.predict()
        return float(p[0][0]), float(p[1][0])

    def velocity(self):
        if not self.initialized:
            return 0.0, 0.0
        return float(self.kf.statePost[2][0]), float(self.kf.statePost[3][0])

    def reset(self):
        self.initialized = False


# ══════════════════════════════════════════════════════════════════
#  TENSORRT INFERENCE
# ══════════════════════════════════════════════════════════════════
class TRTInference:
    def __init__(self, engine_path: str, input_size: int):
        self.input_size = input_size
        logger          = trt.Logger(trt.Logger.ERROR)
        with open(engine_path, 'rb') as f:
            runtime      = trt.Runtime(logger)
            self.engine  = runtime.deserialize_cuda_engine(f.read())
        self.context      = self.engine.create_execution_context()
        self.input_name   = self.engine.get_tensor_name(0)
        self.output_name  = self.engine.get_tensor_name(1)
        self.output_shape = tuple(self.engine.get_tensor_shape(self.output_name))
        self.d_input      = cp.empty((3, input_size, input_size), dtype=cp.float32)
        self.d_output     = cp.empty(self.output_shape, dtype=cp.float32)
        self.stream       = cp.cuda.Stream(non_blocking=True)
        self.context.set_tensor_address(self.input_name,  int(self.d_input.data.ptr))
        self.context.set_tensor_address(self.output_name, int(self.d_output.data.ptr))
        self._warmup()

    def _warmup(self):
        dummy = np.zeros((3, self.input_size, self.input_size), dtype=np.float32)
        self.d_input.set(dummy)
        for _ in range(3):
            self.context.execute_async_v3(stream_handle=self.stream.ptr)
        self.stream.synchronize()
        print("  Warmup complete.")

    def run(self, frame: np.ndarray) -> np.ndarray:
        img = cv2.resize(frame, (self.input_size, self.input_size))
        img = img.transpose((2, 0, 1))
        img = np.ascontiguousarray(img, dtype=np.float32) / 255.0
        self.d_input.set(img)
        self.context.execute_async_v3(stream_handle=self.stream.ptr)
        self.stream.synchronize()
        return self.d_output.get()


# ══════════════════════════════════════════════════════════════════
#  ARDUINO LINK
# ══════════════════════════════════════════════════════════════════
class ArduinoLink:
    """Optional serial link to Arduino gimbal controller."""
    def __init__(self, port, baud, hz):
        self.ok      = False
        self._period = 1.0 / max(hz, 1)
        self._t_last = 0.0
        if not _SERIAL_AVAIL:
            print("  pyserial not installed — pip install pyserial")
            return
        try:
            self._ser = _serial.Serial(port, baud, timeout=0.01)
            time.sleep(0.1)
            self.ok = True
            print(f"  Arduino: {port} @ {baud} baud")
        except Exception as e:
            print(f"  Arduino not found on {port}: {e}")

    def send(self, pan, tilt, locked):
        if not self.ok: return
        now = time.perf_counter()
        if now - self._t_last < self._period: return
        self._t_last = now
        try:
            self._ser.write(f"G{pan:+d},{tilt:+d},{int(locked)}\n".encode())
        except Exception:
            self.ok = False

    def close(self):
        if self.ok:
            try: self._ser.close()
            except Exception: pass


# ══════════════════════════════════════════════════════════════════
#  DARK-PIXEL SEARCH
# ══════════════════════════════════════════════════════════════════
_DARK_SCALE = 0.5   # search at half resolution — ~4× faster

def _sky_brightness(gray_full: np.ndarray) -> float:
    """
    Estimate ambient sky brightness from the top 20 % of the frame.
    Uses the 75th percentile so lone dark birds / blobs don't bias it.
    Works equally on overcast (~120–150), partly cloudy (~160–180),
    and sunny (~190–220) days.
    """
    h = gray_full.shape[0]
    strip = gray_full[:max(1, h // 5), :]
    return float(np.percentile(strip, 75))


_DKERNEL = np.ones((3, 3), np.uint8)   # shared dilation kernel


def dark_pixel_search(gray_full: np.ndarray, kalman: KalmanTracker,
                      cfg: Config, frame_w: int, frame_h: int,
                      sky_ref: float, hint_xy: tuple = None,
                      frame_bgr: np.ndarray = None):
    """
    Find a dark blob that is FULLY surrounded by sky on all four sides.

    Filters applied in order (cheapest first):
      1. Area bounds          — no tiny noise, no massive clouds
      2. Aspect ratio ≤ 3.5  — no contrails, wires, or elongated smears
      3. Frame-edge check     — rejects blobs whose dark path reaches the
                                frame bottom/left/right (full-frame coords
                                used so guided-crop doesn't hide edge objects)
      4. Below-column check   — samples a narrow strip DIRECTLY below the
                                blob using the 10th percentile; a lamp pole
                                or tree trunk darker than sky fails this even
                                when thin (the mean would miss it)
      5. Four-sided sky ring  — top, bottom, left, right strips must ALL
                                average >= sky_ref * SKY_RATIO; any side
                                touching non-sky (ground, pole, branches)
                                fails and the blob is rejected

    Returns (cx, cy, found, blob_list) in full-frame coordinates.
    """
    s    = _DARK_SCALE
    gray = cv2.resize(gray_full, (0, 0), fx=s, fy=s,
                      interpolation=cv2.INTER_AREA)
    sh, sw = gray.shape

    eff_dark_max = int(sky_ref * cfg.DARK_PIXEL_RATIO)
    # Each directional ring strip must average at least this bright.
    # 0.68 × sky keeps overcast/cloudy rings passing while catching
    # poles (~0.55–0.72 × sky) and dark ground (~0.60–0.80 × sky).
    sky_min = sky_ref * 0.68

    # ── Search region: hint > Kalman > full frame ─────────────────
    guided = False
    ox = oy = 0
    if hint_xy is not None:
        # Use np.ravel to ensure hint_xy is a flat 1D array regardless of source
        h_flat = np.ravel(hint_xy)
        px_s, py_s = float(h_flat[0]) * s, float(h_flat[1]) * s
        guided = True
    elif kalman.initialized:
        px_s = float(kalman.kf.statePost[0][0]) * s
        py_s = float(kalman.kf.statePost[1][0]) * s
        guided = True

    if guided:
        r  = cfg.DARK_SEARCH_RADIUS * s
        x1 = max(0,  int(px_s - r));  y1 = max(0,  int(py_s - r))
        x2 = min(sw, int(px_s + r));  y2 = min(sh, int(py_s + r))
        region = gray[y1:y2, x1:x2]
        ox, oy = x1, y1
    else:
        region = gray

    if region.size == 0:
        return 0, 0, False, []

    rh, rw = region.shape

    # Threshold + dilate so thin trunks/poles stay connected to their base
    mask    = (region <= eff_dark_max).astype(np.uint8)
    mask_cc = cv2.dilate(mask, _DKERNEL, iterations=2)

    n, _, stats, centroids = cv2.connectedComponentsWithStats(
        mask_cc, connectivity=8)
    if n < 2:
        return 0, 0, False, []

    min_a  = max(1, int(cfg.DARK_MIN_AREA * s * s))
    max_a  = int(cfg.DARK_MAX_AREA * s * s)
    em     = 3    # frame-edge margin (half-res px)
    ring_m = max(5, int(10 * s))  # ring thickness in region px

    candidates = []
    for i in range(1, n):
        # ── Filter 1: area ────────────────────────────────────────
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_a or area > max_a:
            continue

        bx0 = int(stats[i, cv2.CC_STAT_LEFT])
        by0 = int(stats[i, cv2.CC_STAT_TOP])
        bw  = int(stats[i, cv2.CC_STAT_WIDTH])
        bh  = int(stats[i, cv2.CC_STAT_HEIGHT])

        # ── Filter 2: aspect ratio ────────────────────────────────
        if max(bw, bh) / max(min(bw, bh), 1) > 3.5:
            continue

        # ── Filter 3: frame-edge (full-frame coords) ──────────────
        if by0 + bh + oy >= sh - em: continue  # bottom
        if bx0      + ox <= em:       continue  # left
        if bx0 + bw + ox >= sw - em:  continue  # right

        # ── Filter 4: narrow below-column (catches thin poles) ────
        # Sample the center-HALF of blob width directly below.
        # 15th-percentile: catches poles even when narrower than the blob.
        # A drone has only open sky below → pct ≈ sky brightness.
        below_y = by0 + bh
        if below_y < rh:
            half_w  = max(2, bw // 2)
            cx_blob = bx0 + bw // 2
            col_x1  = max(0,  cx_blob - half_w)
            col_x2  = min(rw, cx_blob + half_w)
            below   = region[below_y : min(rh, below_y + ring_m * 3),
                              col_x1  : col_x2]
            if below.size > 0 and float(np.percentile(below, 15)) < sky_min:
                continue   # something darker than sky directly below → pole

        # ── Filter 5: four-sided sky ring (brightness) ────────────
        # Each directional strip must independently average sky-bright.
        ex1 = max(0,  bx0 - ring_m);  ey1 = max(0,  by0 - ring_m)
        ex2 = min(rw, bx0 + bw + ring_m)
        ey2 = min(rh, by0 + bh + ring_m)

        top_strip    = region[ey1      : by0,       ex1:ex2]
        bottom_strip = region[by0 + bh : ey2,       ex1:ex2]
        left_strip   = region[ey1:ey2,  ex1      : bx0      ]
        right_strip  = region[ey1:ey2,  bx0 + bw : ex2      ]

        sky_ok = True
        for strip in (top_strip, bottom_strip, left_strip, right_strip):
            if strip.size < 4 or float(np.mean(strip)) < sky_min:
                sky_ok = False
                break
        if not sky_ok:
            continue

        # ── Filter 6: blue-sky color ring (optional) ───────────────
        # Sky is blue (B > R). Lamppost metal is neutral gray (B ≈ R).
        # Each directional ring strip is checked in BGR color space.
        # Disable with DARK_COLOR_CHECK=False for fully overcast days
        # where sky is white and B ≈ R.
        if cfg.DARK_COLOR_CHECK and frame_bgr is not None:
            bgr_h = cv2.resize(frame_bgr, (sw, sh), interpolation=cv2.INTER_AREA)
            # ring coords in full half-res frame = region offset + local coords
            def _bgr_strip(r_y1, r_y2, r_x1, r_x2):
                fy1 = oy + r_y1;  fy2 = oy + r_y2
                fx1 = ox + r_x1;  fx2 = ox + r_x2
                return bgr_h[max(0,fy1):min(sh,fy2), max(0,fx1):min(sw,fx2)]

            color_ok = True
            for strip_bgr in (
                _bgr_strip(ey1, by0,       ex1, ex2),   # top
                _bgr_strip(by0+bh, ey2,    ex1, ex2),   # bottom
                _bgr_strip(ey1, ey2,        ex1, bx0),  # left
                _bgr_strip(ey1, ey2,   bx0+bw, ex2),    # right
            ):
                if strip_bgr.size < 6:
                    color_ok = False; break
                b_mean = float(np.mean(strip_bgr[:, :, 0]))
                r_mean = float(np.mean(strip_bgr[:, :, 2]))
                # Sky: B > R by at least 15 counts. Gray pole: B ≈ R.
                if b_mean < r_mean + 15:
                    color_ok = False; break
            if not color_ok:
                continue

        bx = int((centroids[i][0] + ox) / s)
        by = int((centroids[i][1] + oy) / s)
        candidates.append((bx, by, area))

    if not candidates:
        return 0, 0, False, []

    # ── Pick best candidate ───────────────────────────────────────
    if guided:
        h_flat = np.ravel(hint_xy) if hint_xy is not None else None
        px_f = float(h_flat[0] if h_flat is not None else kalman.kf.statePost[0][0])
        py_f = float(h_flat[1] if h_flat is not None else kalman.kf.statePost[1][0])
        diag = (frame_w ** 2 + frame_h ** 2) ** 0.5
        def guided_score(c):
            dist = ((c[0] - px_f) ** 2 + (c[1] - py_f) ** 2) ** 0.5
            prox = 1.0 - min(dist / diag, 1.0)
            return c[2] * (1.0 + 4.0 * prox)
        best = max(candidates, key=guided_score)
    else:
        def cold_score(c):
            vert = c[1] / max(frame_h, 1)
            return c[2] * (1.0 + 2.0 * vert)
        best = min(candidates, key=cold_score)

    return best[0], best[1], True, candidates


# ══════════════════════════════════════════════════════════════════
#  DISPLAY HELPERS
# ══════════════════════════════════════════════════════════════════
def fit_to_screen(vid_w, vid_h, max_w, max_h):
    ratio = min(max_w / vid_w, max_h / vid_h)
    return max(1, int(vid_w * ratio)), max(1, int(vid_h * ratio))

def compute_laser_pos(w, h, cfg: Config):
    return w // 2 + cfg.LASER_OFFSET_X, h // 2 + cfg.LASER_OFFSET_Y

def compute_gimbal_error(cx, cy, lx, ly):
    ex, ey = cx - lx, cy - ly
    return ex, ey, (ex**2 + ey**2) ** 0.5

def refine_to_dark_centroid(gray: np.ndarray,
                            cx: float, cy: float,
                            bw: float, bh: float) -> tuple:
    """
    Snap the CV model centroid to the darkest cluster inside the bbox.

    The model gives a bounding-box centre which includes sky pixels at
    the edges.  The drone body is the darkest mass in that box — its
    centroid is where the laser should actually point.

    Uses pixels within 20 grey levels of the local minimum, so it
    adapts to any lighting condition.  Runs on a small patch so it
    costs < 0.2 ms even at 1080p.

    Returns (refined_cx, refined_cy) in frame pixel coordinates.
    """
    x1 = max(0, int(cx - bw / 2))
    y1 = max(0, int(cy - bh / 2))
    x2 = min(gray.shape[1], int(cx + bw / 2))
    y2 = min(gray.shape[0], int(cy + bh / 2))
    if x2 <= x1 or y2 <= y1:
        return int(cx), int(cy)

    patch  = gray[y1:y2, x1:x2]
    thresh = int(patch.min()) + 20        # darkest cluster ± 20 grey levels
    ys, xs = np.where(patch <= thresh)
    if len(xs) == 0:
        return int(cx), int(cy)

    # Weighted center of mass: darker pixel = heavier weight.
    # This pulls the aim point toward the densest/darkest part of the
    # drone body (motor pods, battery) rather than the geometric mean.
    weights = (thresh - patch[ys, xs].astype(np.int32)).astype(np.float32) + 1.0
    total   = weights.sum()
    rx = float(np.dot(xs.astype(np.float32), weights)) / total
    ry = float(np.dot(ys.astype(np.float32), weights)) / total
    return int(round(rx)) + x1, int(round(ry)) + y1


def _scale_fns(frame):
    h, w = frame.shape[:2]
    s    = min(w / 1920.0, h / 1080.0)   # normalized to 1920×1080 — keeps HUD compact
    S    = lambda n: max(1, int(round(n * s)))
    F    = lambda f: max(0.25, f * s)
    lw   = max(1, int(round(s)))
    tw   = max(1, int(round(s * 1.5)))
    return S, F, lw, tw


# ══════════════════════════════════════════════════════════════════
#  V9 DRAW HELPERS
# ══════════════════════════════════════════════════════════════════
def _draw_trail(show, trail, color):
    """Fading position history dots."""
    n = len(trail)
    if n < 2: return
    for k, (tx, ty) in enumerate(trail):
        alpha = (k + 1) / n
        r = max(1, int(alpha * 5))
        c = tuple(int(v * alpha * 0.75) for v in color)
        cv2.circle(show, (tx, ty), r, c, -1, cv2.LINE_AA)


def _draw_zoom_inset(show, frame, cx, cy, cfg, border_color):
    """Magnified patch around drone in bottom-right corner."""
    crop = max(4, cfg.ZOOM_INSET_SIZE // (2 * cfg.ZOOM_MAGNIFY))
    fh, fw = frame.shape[:2]
    x1 = max(0, cx - crop);  x2 = min(fw, cx + crop)
    y1 = max(0, cy - crop);  y2 = min(fh, cy + crop)
    if x2 <= x1 or y2 <= y1: return
    patch = frame[y1:y2, x1:x2]
    iz    = cfg.ZOOM_INSET_SIZE
    inset = cv2.resize(patch, (iz, iz), interpolation=cv2.INTER_LINEAR)
    ic = iz // 2
    cv2.line(inset,   (ic - 18, ic), (ic + 18, ic), (0, 255, 255), 1, cv2.LINE_AA)
    cv2.line(inset,   (ic, ic - 18), (ic, ic + 18), (0, 255, 255), 1, cv2.LINE_AA)
    cv2.circle(inset, (ic, ic), 9, (0, 0, 255), 1, cv2.LINE_AA)
    sh, sw = show.shape[:2]
    margin = 10
    px1 = sw - iz - margin;  py1 = sh - iz - margin
    if px1 < 0 or py1 < 0: return
    cv2.putText(show, f"{cfg.ZOOM_MAGNIFY}x ZOOM", (px1, py1 - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, border_color, 1, cv2.LINE_AA)
    cv2.rectangle(show, (px1 - 2, py1 - 2),
                  (px1 + iz + 2, py1 + iz + 2), border_color, 2)
    show[py1:py1 + iz, px1:px1 + iz] = inset




# ══════════════════════════════════════════════════════════════════
#  HUD DRAWING
# ══════════════════════════════════════════════════════════════════
def _draw_hud(show, cx, cy, laser_x, laser_y,
              status, color, fps, peak_ms, conf,
              lost_frames, frame_num,
              vx, vy, dark_blobs, sky_ref,
              arduino_ok, cfg: Config, dwell_progress: float = 0.0):
    S, F, lw, tw = _scale_fns(show)

    # Dark blob candidates
    if cfg.SHOW_DARK_BLOBS:
        for bx, by, _ in dark_blobs:
            cv2.circle(show, (bx, by), S(7), (80, 80, 255), lw, cv2.LINE_AA)

    # Offset line laser→drone (thin dashed)
    if cfg.SHOW_OFFSET_LINE and status not in ("SEARCHING", "PREDICTING"):
        ex, ey = cx - laser_x, cy - laser_y
        if ex != 0 or ey != 0:
            pts = np.linspace(0, 1, 20)
            p1, p2 = np.array([laser_x, laser_y]), np.array([cx, cy])
            for k in range(0, len(pts) - 1, 2):
                s0 = tuple((p1 + pts[k]   * (p2 - p1)).astype(int))
                s1 = tuple((p1 + pts[k+1] * (p2 - p1)).astype(int))
                cv2.line(show, s0, s1, (0, 200, 255), 1, cv2.LINE_AA)

    # Laser marker
    if cfg.SHOW_LASER_CENTER:
        cv2.drawMarker(show, (laser_x, laser_y),
                       (255, 255, 0), cv2.MARKER_DIAMOND, S(18), lw, cv2.LINE_AA)
        cv2.drawMarker(show, (laser_x, laser_y),
                       (255, 255, 0), cv2.MARKER_CROSS,   S(24), lw, cv2.LINE_AA)

    # Crosshair + dot — kept small so it doesn't obscure the drone body
    if cfg.SHOW_CROSSHAIR and status != "SEARCHING":
        cv2.drawMarker(show, (cx, cy), color, cv2.MARKER_CROSS, S(28), lw, cv2.LINE_AA)
        cv2.circle(show, (cx, cy), S(4), (0, 0, 255), -1)

    # Lock ring
    if cfg.SHOW_LOCK_RING and status == "LOCKED":
        cv2.circle(show, (cx, cy), S(18), color, lw, cv2.LINE_AA)

    # Dwell kill-confirm arc — fills clockwise from 12 o'clock as on-target time accumulates.
    # Green → yellow → red as it approaches full.  Only visible while actively engaged.
    if dwell_progress > 0.0 and status == "LOCKED":
        r = S(28)   # slightly outside the lock ring
        end_angle = -90 + 360 * dwell_progress
        # Colour: interpolate green→yellow→red  (0% green, 50% yellow, 100% red)
        if dwell_progress < 0.5:
            t = dwell_progress * 2          # 0→1 over first half
            arc_color = (0, int(255 * (1 - t)), int(255 * t))   # green → yellow (BGR)
        else:
            t = (dwell_progress - 0.5) * 2  # 0→1 over second half
            arc_color = (int(255 * t), int(255 * (1 - t)), 0)        # yellow → red (BGR)
        cv2.ellipse(show, (cx, cy), (r, r), 0, -90, end_angle,
                    arc_color, max(lw + 1, 3), cv2.LINE_AA)
        # Countdown text just below the arc
        secs_left = max(0.0, (1.0 - dwell_progress) * 3.0)
        h_show, w_show = show.shape[:2]
        font_scale = F(0.55)
        txt = f'{secs_left:.1f}s'
        tw_ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)[0][0]
        tx = max(0, min(cx - tw_ // 2, w_show - tw_ - 2))
        ty = min(cy + r + S(16), h_show - 4)
        cv2.putText(show, txt, (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, arc_color, tw, cv2.LINE_AA)

    # Velocity arrow — shows predicted heading (short and thin)
    if cfg.SHOW_VELOCITY_ARROW and status in ("LOCKED", "DARK LOCK", "PREDICTING"):
        speed = (vx ** 2 + vy ** 2) ** 0.5
        if speed > 0.3:
            h_show, w_show = show.shape[:2]
            ax = int(cx + vx * 2)
            ay = int(cy + vy * 2)
            ax = max(0, min(ax, w_show - 1))
            ay = max(0, min(ay, h_show - 1))
            cv2.arrowedLine(show, (cx, cy), (ax, ay),
                            (0, 220, 255), lw, cv2.LINE_AA, tipLength=0.35)

    if not cfg.SHOW_HUD_PANEL:
        return

    # ── Text panel ────────────────────────────────────────────────
    mode_map = {
        "LOCKED":     ("CV MODEL",  (0, 255, 100)),
        "DARK LOCK":  ("DARK SRCH", (0, 140, 255)),
        "PREDICTING": ("KALMAN",    (0, 165, 255)),
        "SEARCHING":  ("SEARCHING", (0, 80,  255)),
    }
    mode_lbl, mode_col = mode_map.get(status, ("?", (200, 200, 200)))

    ex, ey, err = compute_gimbal_error(cx, cy, laser_x, laser_y)
    speed = (vx**2 + vy**2) ** 0.5

    lines = [
        (f"FPS:    {int(fps):>4}",               (0, 255, 255)),
        (f"PEAK:   {peak_ms:.0f} ms",
         (0, 80, 255) if peak_ms > 33 else (120, 120, 120)),
        (f"MODE:   {mode_lbl}",                  mode_col),
        (f"STATUS: {status}",                    color),
        (f"CONF:   {conf:.2f}",                  (200, 200, 200)),
        (f"SPEED:  {speed:.1f} px/f",            (200, 200, 200)),
        (f"FRAME:  {frame_num}",                 (150, 150, 150)),
    ]
    if cfg.SHOW_GIMBAL_ERROR:
        lines.append((f"GIMBAL: {ex:+d}px, {ey:+d}px  |{err:.0f}|",
                      (0, 200, 255)))
    if status != "LOCKED":
        lines.append((f"LOST:   {lost_frames} frames", (0, 100, 255)))
    if dark_blobs:
        lines.append((f"BLOBS:  {len(dark_blobs)}", (100, 100, 200)))

    # Arduino status
    if arduino_ok:
        lines.append(("GIMBAL: ONLINE", (0, 200, 255)))

    if cfg.DARK_SEARCH_ENABLED:
        lines.append((f"SKY:    {int(sky_ref)}  dark<{int(sky_ref*cfg.DARK_PIXEL_RATIO)}",
                      (120, 120, 120)))

    fs     = F(0.65)
    row_h  = S(26)
    margin = S(10)
    pad    = S(20)
    pw     = S(460)
    ph     = S(16) + len(lines) * row_h

    cv2.rectangle(show, (margin, margin), (margin+pw, margin+ph), (0,0,0), -1)
    cv2.rectangle(show, (margin, margin), (margin+pw, margin+ph), color, lw)
    for k, (txt, tc) in enumerate(lines):
        y = margin + S(24) + k * row_h
        cv2.putText(show, txt, (pad, y),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, tc, lw, cv2.LINE_AA)


# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════
def main():
    cfg  = Config()
    base = os.path.dirname(os.path.abspath(__file__))

    print("drone_tracking_GPU_v9.py — capstone demo")
    print("Loading TensorRT engine...")
    model = TRTInference(os.path.join(base, cfg.engine_path), cfg.input_size)

    if cfg.USE_LIVE_CAMERA:
        cap          = cv2.VideoCapture(cfg.CAMERA_INDEX)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        total_frames = 0
        print(f"Live camera index {cfg.CAMERA_INDEX}")
    else:
        cap          = cv2.VideoCapture(os.path.join(base, cfg.video_path))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        print(f"Video: {cfg.video_path}  ({total_frames} frames)")

    if not cap.isOpened():
        raise RuntimeError("Cannot open source")

    cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
    fps_src = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # ── Display size — native AR, scale down to fit monitor ───────
    sar_num = cap.get(cv2.CAP_PROP_SAR_NUM)
    sar_den = cap.get(cv2.CAP_PROP_SAR_DEN)
    if sar_num > 0 and sar_den > 0 and abs(sar_num / sar_den - 1.0) > 0.02:
        display_w = max(1, int(width * sar_num / sar_den))
        display_h = height
        print(f"Source {width}×{height}  SAR {int(sar_num)}:{int(sar_den)} → {display_w}×{display_h}")
    else:
        display_w, display_h = width, height
        print(f"Source {width}×{height}")

    needs_resize = (display_w != width or display_h != height)

    reader = FrameReader(cap)

    out = None
    if cfg.SAVE_OUTPUT and not cfg.USE_LIVE_CAMERA:
        sp  = os.path.join(base, cfg.save_path)
        out = cv2.VideoWriter(sp, cv2.VideoWriter_fourcc(*'mp4v'),
                              fps_src, (display_w, display_h))
        print(f"Saving to: {sp}")

    filter_x = OneEuroFilter(cfg.oef_min_cutoff, cfg.oef_beta)
    filter_y = OneEuroFilter(cfg.oef_min_cutoff, cfg.oef_beta)
    kalman   = KalmanTracker()

    trail   = deque(maxlen=cfg.TRAIL_LENGTH)
    arduino = ArduinoLink(cfg.ARDUINO_PORT, cfg.ARDUINO_BAUD, cfg.ARDUINO_HZ) if cfg.ARDUINO_ENABLED else None

    win_w, win_h = fit_to_screen(display_w, display_h,
                                 cfg.MAX_DISPLAY_W, cfg.MAX_DISPLAY_H)
    cv2.namedWindow("LASER_GUIDANCE", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("LASER_GUIDANCE", win_w, win_h)
    print(f"Window {win_w}×{win_h}  |  acquire={cfg.CONF_ACQUIRE}  "
          f"hold={cfg.CONF_HOLD}  dark={'ON' if cfg.DARK_SEARCH_ENABLED else 'OFF'}")
    print("  Keys: q=quit  SPACE=pause  r=reset  s=screenshot")

    avg_fps          = fps_src
    prev_time        = time.perf_counter()
    lost_frames      = 0
    last_conf        = 0.0
    frame_num        = 0
    cx = cy          = 0
    frame_times      = []
    dark_no_conf     = 0      # false-lock guard counter
    dark_grace       = 999    # consecutive dark-miss frames; 999 = grace exhausted
    status           = "SEARCHING"
    color            = (0, 80, 255)

    while True:
        frame = reader.read()
        if frame is None:
            break

        t1        = time.perf_counter()
        dt        = max(t1 - prev_time, 1e-6)
        prev_time = t1
        h, w      = frame.shape[:2]
        frame_num += 1

        # ── Pre-compute grayscale once (shared by model prep + dark search)
        gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sky_ref = _sky_brightness(gray)

        # ── Model inference ───────────────────────────────────────
        raw       = model.run(frame)[0]
        confs     = raw[4, :]
        best_idx  = int(np.argmax(confs))
        best_conf = float(confs[best_idx])

        threshold = cfg.CONF_HOLD if kalman.initialized else cfg.CONF_ACQUIRE

        # Weak model hint: below threshold but above CONF_HINT means the
        # model has a faint idea where the drone is — seed dark search there.
        if cfg.CONF_HINT > 0 and cfg.CONF_HINT <= best_conf < threshold:
            hint_xy = (raw[0, best_idx] * (w / cfg.input_size),
                       raw[1, best_idx] * (h / cfg.input_size))
        else:
            hint_xy = None

        # ── Dark search (run once, reused in all branches) ────────
        dark_blobs: list = []
        dark_found       = False
        dark_cx = dark_cy = 0
        if cfg.DARK_SEARCH_ENABLED and best_conf < threshold:
            dark_cx, dark_cy, dark_found, dark_blobs = dark_pixel_search(
                gray, kalman, cfg, w, h, sky_ref,
                hint_xy=hint_xy, frame_bgr=frame)

        # ── State machine ─────────────────────────────────────────
        if best_conf >= threshold:
            # ── LOCKED (CV model) ─────────────────────────────────
            rx = raw[0, best_idx] * (w / cfg.input_size)
            ry = raw[1, best_idx] * (h / cfg.input_size)
            bw_raw = raw[2, best_idx] * (w / cfg.input_size)
            bh_raw = raw[3, best_idx] * (h / cfg.input_size)
            # Snap to darkest cluster inside the bbox so the laser
            # aims at the drone body, not the edge of the detection box.
            rx, ry = refine_to_dark_centroid(gray, rx, ry, bw_raw, bh_raw)
            cx = int(filter_x.apply(rx, dt))
            cy = int(filter_y.apply(ry, dt))
            kalman.update(cx, cy, dt)
            lost_frames  = 0
            last_conf    = best_conf
            dark_no_conf = 0
            dark_grace   = 999    # grace exhausted while CV is active
            status, color = "LOCKED", (0, 255, 0)

        elif dark_found:
            # ── DARK LOCK (fresh detection) ───────────────────────
            cx = int(filter_x.apply(float(dark_cx), dt))
            cy = int(filter_y.apply(float(dark_cy), dt))
            kalman.update(cx, cy, dt)
            lost_frames  = 0
            last_conf    = 0.0
            dark_grace   = 0    # reset grace — actively finding the drone
            dark_no_conf = 0    # reset false-lock counter — live detection is proof
            status, color = "DARK LOCK", (0, 140, 255)

        elif dark_grace < cfg.DARK_GRACE_FRAMES and kalman.initialized:
            # ── DARK LOCK (grace coast) ───────────────────────────
            # Dark search missed this frame but had a recent lock.
            # Hold position via Kalman for up to DARK_GRACE_FRAMES
            # before dropping to PREDICTING — eliminates flicker.
            dark_grace   += 1
            dark_no_conf += 1   # accumulate only during missed frames
            lost_frames   = 0
            px, py = kalman.predict(dt)
            if px is not None:
                cx, cy = int(px), int(py)
            # False-lock guard: if grace period keeps failing AND CV gives
            # nothing for DARK_LOCK_CONF_TIMEOUT frames, release the lock.
            if dark_no_conf >= cfg.DARK_LOCK_CONF_TIMEOUT:
                dark_no_conf = 0
                dark_grace   = 999
                filter_x.reset(); filter_y.reset(); kalman.reset()
                status, color = "SEARCHING", (0, 80, 255)
            else:
                status, color = "DARK LOCK", (0, 140, 255)

        elif cfg.KALMAN_ENABLED and kalman.initialized and lost_frames < cfg.max_lost_frames:
            # ── PREDICTING (Kalman coast) ─────────────────────────
            px, py = kalman.predict(dt)
            if px is not None:
                cx, cy = int(px), int(py)
            lost_frames += 1
            status, color = "PREDICTING", (0, 165, 255)

        else:
            # ── SEARCHING (full reset) ────────────────────────────
            filter_x.reset(); filter_y.reset(); kalman.reset()
            dark_no_conf = 0
            dark_grace   = 999
            status, color = "SEARCHING", (0, 80, 255)

        # ── Arduino: send frame-space error (not display-space) ───
        laser_x_f = w // 2 + cfg.LASER_OFFSET_X
        laser_y_f = h // 2 + cfg.LASER_OFFSET_Y
        if arduino:
            arduino.send(cx - laser_x_f, cy - laser_y_f,
                         status in ("LOCKED", "DARK LOCK"))

        # ── Timing ───────────────────────────────────────────────
        vx, vy   = kalman.velocity()
        frame_ms = (time.perf_counter() - t1) * 1000
        avg_fps  = 0.05 * (1000.0 / max(frame_ms, 0.1)) + 0.95 * avg_fps
        frame_times.append(frame_ms)
        if len(frame_times) > 60:
            frame_times.pop(0)
        peak_ms = max(frame_times)

        # ── Draw HUD in display-pixel space (no oval distortion) ──
        show = cv2.resize(frame, (display_w, display_h)) if needs_resize else frame.copy()
        sx, sy = display_w / w, display_h / h

        # Map all coordinates to display space
        scx = max(0, min(int(cx * sx), display_w - 1))
        scy = max(0, min(int(cy * sy), display_h - 1))
        laser_x, laser_y = compute_laser_pos(display_w, display_h, cfg)
        blobs_show = [(int(bx*sx), int(by*sy), a) for bx, by, a in dark_blobs]

        # ── Trail ────────────────────────────────────────────────
        if status in ("LOCKED", "DARK LOCK"):
            trail.append((scx, scy))
        elif status == "SEARCHING":
            trail.clear()

        if cfg.SHOW_TRAIL:
            _draw_trail(show, trail, color)

        _draw_hud(show, scx, scy, laser_x, laser_y,
                  status, color, avg_fps, peak_ms, last_conf,
                  lost_frames, frame_num, vx, vy, blobs_show, sky_ref,
                  arduino is not None and (arduino.ok if arduino else False), cfg)

        if cfg.SHOW_ZOOM_INSET and status in ("LOCKED", "DARK LOCK"):
            _draw_zoom_inset(show, frame, cx, cy, cfg, color)

        # ── Save & display ────────────────────────────────────────
        if out:
            out.write(show)
        cv2.imshow("LASER_GUIDANCE", show)

        if not cfg.USE_LIVE_CAMERA and total_frames > 0 and frame_num % 100 == 0:
            pct = frame_num / total_frames * 100
            print(f"  {pct:5.1f}%  f={frame_num}  fps={int(avg_fps)}"
                  f"  peak={peak_ms:.0f}ms  status={status}  blobs={len(dark_blobs)}")

        if cfg.REALTIME_PLAYBACK and not cfg.USE_LIVE_CAMERA:
            elapsed = time.perf_counter() - t1
            wait_ms = max(1, int((1.0 / fps_src - elapsed - 0.001) * 1000))
        else:
            wait_ms = 1

        key = cv2.waitKey(wait_ms) & 0xFF
        if key == ord('q'):
            break
        elif key == ord(' '):
            # ── PAUSE ─────────────────────────────────────────────
            print("  Paused.")
            overlay = show.copy()
            lbl = "|| PAUSED   [SPACE] resume   [Q] quit"
            (tw2, th2), _ = cv2.getTextSize(
                lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
            tx2 = display_w // 2 - tw2 // 2
            ty2 = display_h // 2
            cv2.rectangle(overlay, (tx2 - 12, ty2 - th2 - 12),
                          (tx2 + tw2 + 12, ty2 + 12), (0, 0, 0), -1)
            cv2.putText(overlay, lbl, (tx2, ty2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (0, 255, 255), 2, cv2.LINE_AA)
            cv2.imshow("LASER_GUIDANCE", overlay)
            quit_from_pause = False
            while True:
                k2 = cv2.waitKey(50) & 0xFF
                if k2 == ord('q'):
                    quit_from_pause = True
                    break
                elif k2 == ord(' '):
                    print("  Resumed.")
                    break
            if quit_from_pause:
                break
        elif key == ord('r'):
            filter_x.reset(); filter_y.reset(); kalman.reset()
            trail.clear(); dark_no_conf = 0; dark_grace = 999
            status, color = "SEARCHING", (0, 80, 255)
            print("  Manual reset.")
        elif key == ord('s'):
            fname = os.path.join(base, f"screenshot_{frame_num}.png")
            cv2.imwrite(fname, show)
            print(f"  Screenshot: {fname}")

    reader.stop()
    cap.release()
    if out:
        out.release()
    if arduino:
        arduino.close()
    cv2.destroyAllWindows()
    print("Done.")


if __name__ == "__main__":
    main()
