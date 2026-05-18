"""
hit_confirm_runner.py — Laser-dot calibration & test tool.

Runs the full CVEngine (TRT + Kalman + dark-search + One Euro Filter).
Designed for post-flight tuning: load a video, pause on the frame where
the laser is visible, adjust HSV thresholds until the dot lights up in the
mask, then save the values to HitConfirmConfig.

Scope (bottom-right):
  Full-area mask view — dimmed greyscale with green HSV matches shown in lime.
  Toggle to raw with  M.

  GREEN border  = laser found on THIS frame
  RED border    = not found

Controls box (bottom-left, always visible):
  SPACE        Play / Pause
  . or →       Step forward  1 frame  (pause first)
  , or ←       Step back     1 frame
  ] / [        Playback speed  faster / slower
  + / -        V_LOW  (brightness floor)  ↑ / ↓
  9 / 0        S_LOW  (saturation floor)  ↑ / ↓
  PgUp / PgDn  H_HIGH (hue ceiling)      ↑ / ↓
  Home / End   H_LOW  (hue floor)        ↑ / ↓
  M            Toggle mask / raw
  R            Reset consecutive counter
  Q / ESC      Quit

Usage:
    python hit_confirm_runner.py <video.mp4>
    python hit_confirm_runner.py 1            # live camera at index 1
"""

import sys
import os
import time
from collections import deque

import cv2
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_FCP  = os.path.abspath(os.path.join(_HERE, '..'))
if _FCP not in sys.path:
    sys.path.insert(0, _FCP)

from cv.cv_draw     import Config
from cv.cv_engine   import CVEngine
from cv.hit_confirm import HitConfirmEngine, HitConfirmConfig

# ── Scope display ─────────────────────────────────────────────────────────
SCOPE_PX     = 400    # scope panel size (square)
CROP_RADIUS  = 80     # raw-frame half-width → 160×160 px → 2.5x magnification
SCOPE_MARGIN = 10

# ── Frame history for step-backward ──────────────────────────────────────
HISTORY_LEN = 150     # ~5 s at 30 fps


# ─────────────────────────────────────────────────────────────────────────

def _txt(img, text, pos, colour, scale=0.48, thickness=1):
    x, y = pos
    cv2.putText(img, text, (x+1, y+1), cv2.FONT_HERSHEY_SIMPLEX,
                scale, (0,0,0), thickness+1, cv2.LINE_AA)
    cv2.putText(img, text, (x, y),     cv2.FONT_HERSHEY_SIMPLEX,
                scale, colour,  thickness,   cv2.LINE_AA)


def _build_scope(raw, cx, cy, hc_cfg, show_mask):
    fh, fw = raw.shape[:2]
    x1 = max(0, cx - CROP_RADIUS);  x2 = min(fw, cx + CROP_RADIUS)
    y1 = max(0, cy - CROP_RADIUS);  y2 = min(fh, cy + CROP_RADIUS)
    if x2 <= x1 or y2 <= y1:
        return np.zeros((SCOPE_PX, SCOPE_PX, 3), dtype=np.uint8)

    patch = cv2.resize(raw[y1:y2, x1:x2], (SCOPE_PX, SCOPE_PX),
                       interpolation=cv2.INTER_LINEAR)

    if show_mask:
        # Green channel dominance (same logic as hit_confirm.py)
        b = patch[:, :, 0].astype(np.int16)
        g = patch[:, :, 1].astype(np.int16)
        r = patch[:, :, 2].astype(np.int16)
        dominance = (g - np.maximum(r, b)).clip(0, 255).astype(np.uint8)
        dom_mask  = (dominance >= hc_cfg.GREEN_EXCESS_MIN).astype(np.uint8) * 255

        hsv      = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        hsv_mask = cv2.inRange(
            hsv,
            np.array([hc_cfg.H_LOW,  hc_cfg.S_LOW,  hc_cfg.V_LOW],   dtype=np.uint8),
            np.array([hc_cfg.H_HIGH, 255,            hc_cfg.V_HIGH],  dtype=np.uint8),
        )
        mask = cv2.bitwise_and(dom_mask, hsv_mask)

        gray   = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        dimmed = (gray.astype(np.float32) * 0.35).astype(np.uint8)
        scope  = cv2.cvtColor(dimmed, cv2.COLOR_GRAY2BGR)
        scope[mask > 0] = (0, 255, 80)
    else:
        scope = patch.copy()

    # Crosshair
    ic = SCOPE_PX // 2
    cv2.line(scope,   (ic-20, ic), (ic+20, ic), (0,255,255), 1, cv2.LINE_AA)
    cv2.line(scope,   (ic, ic-20), (ic, ic+20), (0,255,255), 1, cv2.LINE_AA)
    cv2.circle(scope, (ic, ic), 10, (0,0,255),  1, cv2.LINE_AA)

    return scope


def _draw_controls(img, hc_cfg, paused, show_mask, frame_num, hist_pos):
    """Draw controls + current values box in bottom-left corner."""
    lines = [
        ('--- PLAYBACK ---',               (160, 160, 160)),
        (f'SPACE    {"[PAUSED]" if paused else "Play/Pause"}',
         (0,220,255) if paused else (200,200,200)),
        ('. / >    Step forward',          (200, 200, 200)),
        (', / <    Step back',             (200, 200, 200)),
        ('',                               (0,0,0)),
        ('--- DETECTION THRESHOLDS ---',    (160, 160, 160)),
        (f'Z / X    G_EXCESS= {hc_cfg.GREEN_EXCESS_MIN}', (0,255,180)),
        (f'+ / -    V_LOW  = {hc_cfg.V_LOW}',   (0,220,80)),
        (f'V / B    V_HIGH = {hc_cfg.V_HIGH}',  (0,220,80)),
        (f'9 / 0    S_LOW  = {hc_cfg.S_LOW}',   (0,220,80)),
        (f'PgUp/Dn  H_HIGH = {hc_cfg.H_HIGH}',  (0,220,80)),
        (f'Home/End H_LOW  = {hc_cfg.H_LOW}',   (0,220,80)),
        ('',                               (0,0,0)),
        ('--- VIEW ---',                   (160, 160, 160)),
        (f'M        {"[MASK]" if show_mask else "[RAW]"}',
         (0,255,80) if show_mask else (200,200,200)),
        ('R        Reset counter',         (200, 200, 200)),
        ('Q        Quit',                  (200, 200, 200)),
    ]
    if hist_pos >= 0:
        lines.insert(0, (f'[HISTORY frame {frame_num}]', (0,180,255)))

    scale  = 0.55
    lh     = 22
    pad    = 10
    box_w  = 280
    box_h  = len(lines) * lh + pad * 2
    ih, iw = img.shape[:2]
    bx     = pad
    by     = ih - box_h - pad

    # Semi-transparent background
    overlay = img.copy()
    cv2.rectangle(overlay, (bx, by), (bx + box_w, by + box_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.75, img, 0.25, 0, img)
    cv2.rectangle(img, (bx, by), (bx + box_w, by + box_h), (80, 80, 80), 1)

    for i, (text, col) in enumerate(lines):
        if text:
            _txt(img, text, (bx + pad, by + pad + lh // 2 + i * lh), col, scale=scale)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    src       = sys.argv[1]
    is_camera = src.isdigit()

    if is_camera:
        cv_cfg = Config(USE_LIVE_CAMERA=True, CAMERA_INDEX=int(src),
                        SHOW_ZOOM_INSET=False)
        engine = CVEngine(video_path=None, cfg=cv_cfg)
    else:
        cv_cfg = Config(SHOW_ZOOM_INSET=False)
        engine = CVEngine(video_path=src, cfg=cv_cfg)

    engine.start()
    print('[runner] CVEngine started — waiting for TRT...')

    hc_cfg = HitConfirmConfig(
        SEARCH_RADIUS_FALLBACK=CROP_RADIUS,
        H_LOW=50, H_HIGH=100,
        S_LOW=20, V_LOW=60,
        MAX_AREA_PX=800,
    )
    # Use process_frame directly — per-frame, no accumulation.
    # This makes tuning immediate: threshold change = instant scope response.
    hc = HitConfirmEngine(hc_cfg)

    # ── State ─────────────────────────────────────────────────────────
    paused     = False
    show_mask  = True
    got_first  = False
    frame_num  = 0

    # Frame history for step-backward
    history: deque = deque(maxlen=HISTORY_LEN)
    hist_pos  = -1            # -1 = live; >=0 = browsing history

    # Cached for pause/tuning — scope re-renders live from this when paused
    cached_raw  = None
    cached_cx   = cached_cy = 0
    cached_bw   = cached_bh = 0
    cached_annot = None

    # Step-forward request: grab 1 frame then re-pause
    step_fwd    = False
    step_bck    = False

    t_start = time.perf_counter()

    cv2.namedWindow('Hit Confirm Runner', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('Hit Confirm Runner', 1280, 720)

    while True:
        # ── Key handling ──────────────────────────────────────────────
        key = cv2.waitKey(1) & 0xFF

        if key in (ord('q'), 27):
            break

        elif key == ord(' '):
            paused = not paused
            if not paused:
                hist_pos = -1   # return to live on resume

        elif key in (ord('.'), 83):    # '.' or right-arrow
            paused   = True
            step_fwd = True

        elif key in (ord(','), 81):    # ',' or left-arrow
            paused   = True
            step_bck = True

        elif key == ord('z'):
            hc_cfg.GREEN_EXCESS_MIN = max(1, hc_cfg.GREEN_EXCESS_MIN - 1)
        elif key == ord('x'):
            hc_cfg.GREEN_EXCESS_MIN = min(80, hc_cfg.GREEN_EXCESS_MIN + 1)

        elif key == ord('v'):
            hc_cfg.V_HIGH = min(254, hc_cfg.V_HIGH + 5)
        elif key == ord('b'):
            hc_cfg.V_HIGH = max(hc_cfg.V_LOW + 1, hc_cfg.V_HIGH - 5)

        elif key in (ord('+'), ord('=')):
            hc_cfg.V_LOW = min(254, hc_cfg.V_LOW + 5)
        elif key == ord('-'):
            hc_cfg.V_LOW = max(0, hc_cfg.V_LOW - 5)

        elif key == ord('9'):
            hc_cfg.S_LOW = min(254, hc_cfg.S_LOW + 5)
        elif key == ord('0'):
            hc_cfg.S_LOW = max(0, hc_cfg.S_LOW - 5)

        elif key == 85:   # PgUp
            hc_cfg.H_HIGH = min(179, hc_cfg.H_HIGH + 2)
        elif key == 86:   # PgDn
            hc_cfg.H_HIGH = max(hc_cfg.H_LOW + 1, hc_cfg.H_HIGH - 2)

        elif key == 80:   # Home
            hc_cfg.H_LOW = max(0, hc_cfg.H_LOW - 2)
        elif key == 87:   # End
            hc_cfg.H_LOW = min(hc_cfg.H_HIGH - 1, hc_cfg.H_LOW + 2)

        elif key == ord('m'):
            show_mask = not show_mask

        elif key == ord('r'):
            hc.reset()
            print(f'[frame {frame_num}] reset')

        # ── Step backward through history ─────────────────────────────
        if step_bck and len(history) > 0:
            step_bck = False
            if hist_pos < 0:
                hist_pos = len(history) - 1          # jump to most recent cached
            elif hist_pos > 0:
                hist_pos -= 1
            h = history[hist_pos]
            cached_raw   = h['raw']
            cached_cx    = h['cx'];  cached_cy = h['cy']
            cached_bw    = h['bw'];  cached_bh = h['bh']
            cached_annot = h['annot']
            frame_num    = h['frame_num']

        # ── Step forward through history or live ──────────────────────
        if step_fwd:
            step_fwd = False
            if hist_pos >= 0:
                if hist_pos < len(history) - 1:
                    hist_pos += 1
                    h = history[hist_pos]
                    cached_raw   = h['raw']
                    cached_cx    = h['cx'];  cached_cy = h['cy']
                    cached_bw    = h['bw'];  cached_bh = h['bh']
                    cached_annot = h['annot']
                    frame_num    = h['frame_num']
                else:
                    hist_pos = -1   # reached end of history — go live
            else:
                # Live step: pull one real frame then re-pause
                annot = engine.read_frame()
                if annot is not None:
                    meta = engine.get_metadata()
                    raw  = engine.get_raw_frame()
                    if raw is not None:
                        frame_num   += 1
                        cached_raw   = raw
                        cached_cx    = meta['cx'];  cached_cy = meta['cy']
                        cached_bw    = meta.get('bbox_w',0)
                        cached_bh    = meta.get('bbox_h',0)
                        cached_annot = annot
                        history.append(dict(raw=raw, cx=meta['cx'], cy=meta['cy'],
                                            bw=cached_bw, bh=cached_bh,
                                            annot=annot, frame_num=frame_num))

        # ── Normal playback: pull frame from engine ───────────────────
        if not paused and hist_pos < 0:
            err = engine.get_error()
            if err:
                print(f'[runner] CVEngine error: {err}')
                break

            annot = engine.read_frame()
            if annot is None:
                if not got_first:
                    # Loading screen
                    wait_s = time.perf_counter() - t_start
                    loading = np.zeros((720, 1280, 3), dtype=np.uint8)
                    _txt(loading, 'Loading TRT engine...',
                         (440, 340), (200,200,200), scale=1.0, thickness=2)
                    _txt(loading, f'{wait_s:.1f}s',
                         (595, 390), (150,150,150), scale=0.8)
                    cv2.imshow('Hit Confirm Runner', loading)
                time.sleep(0.005)
                continue

            got_first  = True
            meta       = engine.get_metadata()
            raw        = engine.get_raw_frame()

            if raw is not None:
                frame_num   += 1
                cached_raw   = raw
                cached_cx    = meta['cx'];  cached_cy = meta['cy']
                cached_bw    = meta.get('bbox_w', 0)
                cached_bh    = meta.get('bbox_h', 0)
                cached_annot = annot
                history.append(dict(raw=raw, cx=meta['cx'], cy=meta['cy'],
                                    bw=cached_bw, bh=cached_bh,
                                    annot=annot, frame_num=frame_num))


        # ── Nothing to render yet ─────────────────────────────────────
        if cached_raw is None:
            time.sleep(0.01)
            continue

        # ── Detect on current (cached) frame ──────────────────────────
        # process_frame only — per-frame, no accumulation, instant feedback
        found, hc_conf, _ = hc.process_frame(
            cached_raw, cached_cx, cached_cy, cached_bw, cached_bh)

        # ── Build scope ───────────────────────────────────────────────
        scope = _build_scope(cached_raw, cached_cx, cached_cy, hc_cfg, show_mask)

        fh, fw  = cached_annot.shape[:2]
        px1     = fw - SCOPE_PX - SCOPE_MARGIN
        py1     = fh - SCOPE_PX - SCOPE_MARGIN

        display = cached_annot.copy()

        if px1 >= 0 and py1 >= 0:
            display[py1:py1+SCOPE_PX, px1:px1+SCOPE_PX] = scope

            col, label, thick = (
                ((0,255,0),   'LASER DETECTED', 3) if found else
                ((0,0,220),   'NO LASER',        2)
            )
            cv2.rectangle(display,
                          (px1-2, py1-2),
                          (px1+SCOPE_PX+2, py1+SCOPE_PX+2),
                          col, thick)
            _txt(display, 'SCOPE',   (px1, py1-20), (180,180,180), scale=0.4)
            _txt(display, label,     (px1, py1-5),  col, scale=0.65, thickness=2)
            mode_lbl = 'MASK' if show_mask else 'RAW'
            _txt(display, mode_lbl,  (px1+SCOPE_PX-38, py1-5), (160,160,160), scale=0.4)


            # Consecutive counter
            _txt(display, f'{hc._consecutive}/{hc_cfg.CONFIRM_FRAMES}',
                 (px1+4, py1+16), col, scale=0.5)

        # ── Controls box (bottom-left) ────────────────────────────────
        _draw_controls(display, hc_cfg, paused or hist_pos >= 0,
                       show_mask, frame_num, hist_pos)

        # ── Frame / FPS strip ─────────────────────────────────────────
        state = engine.get_metadata().get('state', '?')
        _txt(display,
             f'frame={frame_num}  cv={state}  conf={hc_conf:.2f}',
             (10, 20), (160,160,160), scale=0.45)

        cv2.imshow('Hit Confirm Runner', display)

    engine.stop()
    cv2.destroyAllWindows()
    print(f'\nFinal thresholds:  H=[{hc_cfg.H_LOW},{hc_cfg.H_HIGH}]  '
          f'S>={hc_cfg.S_LOW}  V>={hc_cfg.V_LOW}')


if __name__ == '__main__':
    main()
