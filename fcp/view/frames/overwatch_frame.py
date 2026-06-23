"""
overwatch_frame.py — Raw field-view camera tab, no CV.

A second, laptop-mounted camera giving a plain situational view of the
field (as opposed to the DNE-mounted camera the CV engine tracks through).
No inference runs on this feed — it's just a live passthrough. Capture
only runs while this tab is the active one (start()/stop() are driven by
VideoFrame's tab-change handler), so it doesn't burn CPU/USB bandwidth
sitting in the background.

Device selection: configured via config.ini [overwatch.camera] device —
prefer a stable /dev/v4l/by-id/... path over a bare index when more than
one camera may be attached, since plain indices can silently swap between
cameras depending on attach order (the same issue solved for DNE serial
ports via /dev/serial/by-id/).
"""

import configparser
import os

import cv2
from PyQt6.QtWidgets import QVBoxLayout, QLabel, QSizePolicy
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap

from view.frames.base_frame import BaseFrame
from cv.camera_capture import open_live_camera

_BG = '#F0F0F0'
_DIM = '#757575'


def _load_device_config() -> str | int:
    cfg_path = os.path.join(os.path.dirname(__file__), '..', '..', 'cfg', 'config.ini')
    parser = configparser.ConfigParser()
    parser.read(cfg_path)
    device = parser.get('overwatch.camera', 'device', fallback='1')
    return int(device) if device.isdigit() else device


class OverwatchFrame(BaseFrame):
    """Raw camera passthrough — no annotation, no inference."""

    _POLL_MS = 66   # ~15fps — plenty for a situational field-overview feed

    def __init__(self, parent=None):
        self._cap = None        # camera_capture.LiveCapture instance, or None
        self._pixmap: QPixmap | None = None
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._grab_frame)
        self._set_idle('Overwatch camera not active — select this tab to connect')

    # ------------------------------------------------------------------

    def create_widgets(self):
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._img_label.setMinimumSize(1, 1)
        self._img_label.setStyleSheet(f'background:{_BG}; color:{_DIM}; font:10pt Helvetica;')
        vbox.addWidget(self._img_label)

    # ------------------------------------------------------------------
    # Public API — start/stop tied to tab visibility
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the configured camera and begin streaming. No-op if already running."""
        if self._cap is not None:
            return
        device = _load_device_config()
        self._set_idle(f'Connecting to overwatch camera ({device})…')
        cap, err = open_live_camera(device, log_prefix='[Overwatch]')
        if cap is None:
            self._set_idle(f'Overwatch camera not connected: {err}')
            return
        self._cap = cap
        self._timer.start(self._POLL_MS)

    def stop(self) -> None:
        """Release the camera. Called when switching away from this tab."""
        self._timer.stop()
        if self._cap is not None:
            self._cap.stop()
            self._cap = None
        self._set_idle('Overwatch camera not active — select this tab to connect')

    # ------------------------------------------------------------------

    def _grab_frame(self) -> None:
        if self._cap is None:
            return
        frame = self._cap.read()
        if frame is None:
            return
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame_rgb.shape
        img = QImage(frame_rgb.data, w, h, w * ch, QImage.Format.Format_RGB888)
        self._display_pixmap(QPixmap.fromImage(img))

    def _display_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._img_label.setText('')
        self._img_label.setPixmap(pixmap.scaled(
            self._img_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def _set_idle(self, message: str) -> None:
        self._pixmap = None
        self._img_label.setPixmap(QPixmap())
        self._img_label.setText(message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap is not None:
            self._display_pixmap(self._pixmap)
