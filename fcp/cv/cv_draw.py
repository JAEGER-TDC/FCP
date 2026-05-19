"""
cv_draw.py — HUD drawing functions and Config extracted from cv.py.

No TensorRT or CuPy imports — safe to use on any hardware.
All functions are copied verbatim from cv.py so the simulator
produces the same visual output as the real engine.
"""

import cv2
import numpy as np
from dataclasses import dataclass


# ══════════════════════════════════════════════════════════════════
#  CONFIGURATION  — every tunable in one place
# ══════════════════════════════════════════════════════════════════
@dataclass
class Config:

    # ── Source ────────────────────────────────────────────────────
    USE_LIVE_CAMERA:    bool  = False
    CAMERA_INDEX:       int   = 0
    video_path:         str   = "RAT-CV-1.mp4"
    save_path:          str   = ".mp4"
    SAVE_OUTPUT:        bool  = False

    # ── TensorRT model ────────────────────────────────────────────
    engine_path:        str   = "best.engine"
    input_size:         int   = 320

    # ── CV confidence thresholds ──────────────────────────────────
    CONF_ACQUIRE:       float = 0.25
    CONF_HOLD:          float = 0.10
    CONF_HINT:          float = 0.05

    # ── Kalman coast (PREDICTING mode) ────────────────────────────
    KALMAN_ENABLED:     bool  = True
    max_lost_frames:    int   = 100

    # ── Dark-pixel search ─────────────────────────────────────────
    DARK_SEARCH_ENABLED:  bool  = True
    DARK_PIXEL_RATIO:     float = 0.55
    DARK_MIN_AREA:        int   = 150
    DARK_MAX_AREA:        int   = 20000
    DARK_SEARCH_RADIUS:   int   = 300
    DARK_COLOR_CHECK:     bool  = True

    # ── Dark lock hysteresis ──────────────────────────────────────
    DARK_GRACE_FRAMES:    int   = 10

    # ── False-lock guard ──────────────────────────────────────────
    DARK_LOCK_CONF_TIMEOUT: int = 20

    # ── Laser / Gimbal physical offset ───────────────────────────
    LASER_OFFSET_X:     int   = 0
    LASER_OFFSET_Y:     int   = 0

    # ── Position smoothing ────────────────────────────────────────
    oef_min_cutoff:     float = 0.05
    oef_beta:           float = 0.002

    # ── Display ───────────────────────────────────────────────────
    MAX_DISPLAY_W:      int   = 1728
    MAX_DISPLAY_H:      int   = 972
    REALTIME_PLAYBACK:  bool  = True

    # ── Arduino / Gimbal serial output ───────────────────────────
    ARDUINO_ENABLED:    bool  = False
    ARDUINO_PORT:       str   = "COM3"
    ARDUINO_BAUD:       int   = 115200
    ARDUINO_HZ:         int   = 30

    # ── Engagement threshold ──────────────────────────────────────
    ENGAGE_RADIUS_PX:   int   = 40

    # ── HUD overlay toggles ───────────────────────────────────────
    SHOW_HUD_PANEL:     bool  = False
    SHOW_FPS:           bool  = False
    SHOW_CROSSHAIR:     bool  = True
    SHOW_LOCK_RING:     bool  = True
    SHOW_LASER_CENTER:  bool  = True
    SHOW_OFFSET_LINE:   bool  = True
    SHOW_GIMBAL_ERROR:  bool  = True
    SHOW_DARK_BLOBS:    bool  = True

    # ── Visual extras ─────────────────────────────────────────────
    SHOW_TRAIL:         bool  = True
    TRAIL_LENGTH:       int   = 60
    SHOW_ZOOM_INSET:    bool  = False
    ZOOM_INSET_SIZE:    int   = 160
    ZOOM_MAGNIFY:       int   = 2
    SHOW_VELOCITY_ARROW: bool = True


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


def _scale_fns(frame):
    h, w = frame.shape[:2]
    s    = min(w / 1920.0, h / 1080.0)
    S    = lambda n: max(1, int(round(n * s)))
    # Floor font at 0.42 so text stays legible on low-res camera frames
    F    = lambda f: max(0.42, f * s)
    lw   = max(1, int(round(s)))
    tw   = max(1, int(round(s * 1.5)))
    return S, F, lw, tw


# ══════════════════════════════════════════════════════════════════
#  DRAW HELPERS
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
    sh, sw = show.shape[:2]
    # Scale inset size proportionally — nominal size is for 1080p, scale down for smaller frames
    iz   = max(80, int(cfg.ZOOM_INSET_SIZE * min(sh / 1080.0, sw / 1920.0)))
    crop = max(4, iz // (2 * cfg.ZOOM_MAGNIFY))
    fh, fw = frame.shape[:2]
    x1 = max(0, cx - crop);  x2 = min(fw, cx + crop)
    y1 = max(0, cy - crop);  y2 = min(fh, cy + crop)
    if x2 <= x1 or y2 <= y1: return
    patch = frame[y1:y2, x1:x2]
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
              arduino_ok, cfg: Config):
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

    # Crosshair + dot
    if cfg.SHOW_CROSSHAIR and status != "SEARCHING":
        cv2.drawMarker(show, (cx, cy), color, cv2.MARKER_CROSS, S(28), lw, cv2.LINE_AA)
        cv2.circle(show, (cx, cy), S(4), (0, 0, 255), -1)

    # Lock ring
    if cfg.SHOW_LOCK_RING and status == "LOCKED":
        cv2.circle(show, (cx, cy), S(18), color, lw, cv2.LINE_AA)

    # Velocity arrow
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

    if arduino_ok:
        lines.append(("GIMBAL: ONLINE", (0, 200, 255)))

    if cfg.DARK_SEARCH_ENABLED:
        lines.append((f"SKY:    {int(sky_ref)}  dark<{int(sky_ref*cfg.DARK_PIXEL_RATIO)}",
                      (120, 120, 120)))

    fs     = F(0.65)
    row_h  = max(20, S(26))   # never less than 20px — prevents line overlap
    margin = max(6, S(10))
    pad    = max(10, S(20))
    pw     = max(200, S(460))
    ph     = max(20, S(16)) + len(lines) * row_h

    cv2.rectangle(show, (margin, margin), (margin+pw, margin+ph), (0,0,0), -1)
    cv2.rectangle(show, (margin, margin), (margin+pw, margin+ph), color, lw)
    for k, (txt, tc) in enumerate(lines):
        y = margin + S(24) + k * row_h
        cv2.putText(show, txt, (pad, y),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, tc, lw, cv2.LINE_AA)
