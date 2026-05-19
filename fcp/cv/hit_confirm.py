"""
hit_confirm.py — Green laser dot detection for hit confirmation.

HitConfirmEngine scans a bounding-box-sized ROI around the tracked drone
centroid for bright green pixels (the laser dot). It accumulates detections
across consecutive frames before declaring a confirmed hit to suppress noise.

Usage (standalone):  see hit_confirm_runner.py
Usage (GUI):         controller instantiates HitConfirmEngine on engage,
                     calls update() each CV poll cycle, acts on confirmed=True.
"""

import cv2
import numpy as np
from dataclasses import dataclass


@dataclass
class HitConfirmConfig:
    # ── Green channel dominance (primary — catches faint dots) ───────────
    # Fires when G - max(R, B) >= GREEN_EXCESS_MIN.
    # Lower = more sensitive.  Start ~8, raise to suppress false positives.
    GREEN_EXCESS_MIN: int = 8

    # ── Brightness window — isolates dark surfaces (drone body / payload) ─
    # Grass and sky are BRIGHT. The drone body and its shadow are DARK.
    # A laser dot on a shadowed surface will be dim but slightly brighter
    # than its immediate surroundings.
    # V_LOW:  ignore pixels darker than this (sensor noise floor)
    # V_HIGH: ignore pixels brighter than this (sky, grass, sunlit surfaces)
    V_LOW:  int = 20
    V_HIGH: int = 140   # tune down if the drone body is still too bright

    # ── HSV hue gate (secondary — removes non-green hues that pass dominance)
    H_LOW:  int = 35
    H_HIGH: int = 85
    S_LOW:  int = 0

    # ── Green dot size limits (pixels in original frame resolution) ───────
    MIN_AREA_PX: int = 2    # ignore sub-pixel noise
    MAX_AREA_PX: int = 300  # ignore large green blobs (vegetation etc.)

    # ── Search window around drone centroid ───────────────────────────────
    # Actual radius = max(bbox_w, bbox_h) / 2 + BBOX_PADDING, or
    # SEARCH_RADIUS_FALLBACK when no bbox is available.
    BBOX_PADDING:           int = 20
    SEARCH_RADIUS_FALLBACK: int = 80

    # ── Consecutive-frame accumulation before declaring confirmed hit ─────
    CONFIRM_FRAMES: int = 3


class HitConfirmEngine:
    """Detect a small green laser dot on the tracked drone body."""

    def __init__(self, cfg: HitConfirmConfig | None = None):
        self._cfg         = cfg or HitConfirmConfig()
        self._consecutive = 0   # frames in a row with a detected dot
        self._confirmed   = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset consecutive counter and confirmed flag."""
        self._consecutive = 0
        self._confirmed   = False

    def process_frame(
        self,
        frame_bgr: np.ndarray,
        cx: int,
        cy: int,
        bbox_w: int = 0,
        bbox_h: int = 0,
    ) -> tuple[bool, float, np.ndarray]:
        """Analyse one frame for a green laser dot near (cx, cy).

        Returns
        -------
        dot_found : bool
        confidence : float  0.0–1.0
        debug_roi  : np.ndarray  — copy of the ROI with any detection drawn on it
        """
        cfg = self._cfg
        h, w = frame_bgr.shape[:2]

        # Compute search radius
        if bbox_w > 0 or bbox_h > 0:
            radius = max(bbox_w, bbox_h) // 2 + cfg.BBOX_PADDING
        else:
            radius = cfg.SEARCH_RADIUS_FALLBACK

        # Clamp ROI to frame bounds
        x0 = max(0, cx - radius)
        y0 = max(0, cy - radius)
        x1 = min(w, cx + radius)
        y1 = min(h, cy + radius)

        if x1 <= x0 or y1 <= y0:
            return False, 0.0, np.zeros((1, 1, 3), dtype=np.uint8)

        roi = frame_bgr[y0:y1, x0:x1].copy()

        # ── Green channel dominance mask (primary — catches faint dots) ───
        b = roi[:, :, 0].astype(np.int16)
        g = roi[:, :, 1].astype(np.int16)
        r = roi[:, :, 2].astype(np.int16)
        dominance = (g - np.maximum(r, b)).clip(0, 255).astype(np.uint8)
        dom_mask  = (dominance >= cfg.GREEN_EXCESS_MIN).astype(np.uint8) * 255

        # ── HSV gate: hue + brightness window ────────────────────────────
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hsv_mask = cv2.inRange(
            hsv,
            np.array([cfg.H_LOW,  cfg.S_LOW,  cfg.V_LOW],  dtype=np.uint8),
            np.array([cfg.H_HIGH, 255,         cfg.V_HIGH], dtype=np.uint8),
        )

        # Combined: must pass dominance AND hue/brightness gate
        mask = cv2.bitwise_and(dom_mask, hsv_mask)

        # Morphological clean-up — close tiny gaps, remove single-pixel noise
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_area = 0.0
        best_cnt  = None
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < cfg.MIN_AREA_PX or area > cfg.MAX_AREA_PX:
                continue
            # Circularity filter — laser dot should be roughly round
            perim = cv2.arcLength(cnt, True)
            if perim > 0:
                circularity = 4 * np.pi * area / (perim ** 2)
                if circularity < 0.2:
                    continue
            if area > best_area:
                best_area = area
                best_cnt  = cnt

        found      = best_cnt is not None
        confidence = min(best_area / cfg.MAX_AREA_PX, 1.0) if found else 0.0

        # Annotate debug ROI
        cv2.rectangle(roi, (0, 0), (roi.shape[1] - 1, roi.shape[0] - 1), (0, 255, 0), 1)
        if found:
            cv2.drawContours(roi, [best_cnt], -1, (0, 255, 0), 2)
            M = cv2.moments(best_cnt)
            if M['m00'] > 0:
                dcx = int(M['m10'] / M['m00'])
                dcy = int(M['m01'] / M['m00'])
                cv2.circle(roi, (dcx, dcy), 6, (0, 0, 255), 2)

        return found, confidence, roi

    def update(
        self,
        frame_bgr: np.ndarray,
        cx: int,
        cy: int,
        bbox_w: int = 0,
        bbox_h: int = 0,
    ) -> tuple[bool, float]:
        """Process one frame and track consecutive detections.

        Returns (confirmed, confidence).
        confirmed becomes True once CONFIRM_FRAMES consecutive detections occur
        and stays True until reset() is called.
        """
        found, conf, _ = self.process_frame(frame_bgr, cx, cy, bbox_w, bbox_h)
        if found:
            self._consecutive += 1
            if self._consecutive >= self._cfg.CONFIRM_FRAMES:
                self._confirmed = True
        else:
            self._consecutive = 0
        return self._confirmed, conf
