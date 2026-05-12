import os
import cv2
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QWidget, QPushButton,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from view.frames.base_frame import BaseFrame

ASPECT = 16 / 9


class VideoFrame(BaseFrame):
    """Shows a video stream (or static image) that always fills the panel."""
    _PAD = 8

    def __init__(self, parent=None):
        self._cap                 = None   # cv2.VideoCapture instance
        self._cv_engine           = None   # CVEngineBase instance (engine mode)
        self._running             = False
        self._delay_ms            = 33
        self._pixmap              = None   # latest QPixmap, kept for resize repaints
        self._load_callback       = None
        self._alert_callback      = None
        self._tuning_panel        = None
        self._pause_overlay_shown = False

        super().__init__(parent)

        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._grab_frame)

        self._set_placeholder()

    # ------------------------------------------------------------------
    # Widget construction (called by BaseFrame.__init__)
    # ------------------------------------------------------------------

    def create_widgets(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._img_label.setMinimumSize(1, 1)
        layout.addWidget(self._img_label)

        self._cv_status_label = QLabel('CV: SEARCHING  0.00', self)
        self._cv_status_label.setStyleSheet(
            'color: #FF3030; background: rgba(0,0,0,150); '
            'padding: 2px 8px; font: bold 11px monospace; border-radius: 3px;')
        self._cv_status_label.move(8, 8)
        self._cv_status_label.raise_()
        self._cv_status_label.show()

        # Floating button bar (top-right corner, positioned via move())
        self._btn_bar = QWidget(self)
        _bl = QHBoxLayout(self._btn_bar)
        _bl.setContentsMargins(4, 4, 4, 4)
        _bl.setSpacing(4)
        self._load_btn = QPushButton('Load Video')
        self._load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_btn.setStyleSheet(
            'background:#1a1a2e; color:white; border:none;'
            ' padding:2px 6px; font:bold 9pt Helvetica;')
        self._load_btn.clicked.connect(self._on_load_clicked)
        self._gear_btn = QPushButton('⚙')
        self._gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gear_btn.setStyleSheet(
            'background:#1a1a2e; color:#7ec8e3; border:none;'
            ' padding:2px 4px; font:13pt Helvetica;')
        self._gear_btn.clicked.connect(self._on_gear_clicked)
        _bl.addWidget(self._load_btn)
        _bl.addWidget(self._gear_btn)
        self._btn_bar.adjustSize()
        self._btn_bar.raise_()

        # Pause overlay (centered, hidden until engine is paused)
        self._pause_overlay = QWidget(self)
        self._pause_overlay.setStyleSheet(
            'background:rgba(13,13,26,230); border:1px solid #7ec8e3;')
        _ol = QVBoxLayout(self._pause_overlay)
        _lbl = QLabel(
            '⏸  PAUSED\n\n'
            '  SPACE    Resume\n'
            '  R            Reset Tracking\n'
            '  V            Restart Video\n'
            '  Q            Quit')
        _lbl.setStyleSheet('color:#e0e0e0; font:12pt Courier;')
        _ol.addWidget(_lbl)
        self._pause_overlay.adjustSize()
        self._pause_overlay.hide()

    # ------------------------------------------------------------------
    # Resize — repaint cached pixmap + reposition floating widgets
    # ------------------------------------------------------------------

    def update_cv_status(self, state: str, confidence: float) -> None:
        colours = {
            'LOCKED':     '#00FF00',
            'DARK LOCK':  '#FF8C00',
            'PREDICTING': '#FFA500',
            'SEARCHING':  '#FF3030',
        }
        colour = colours.get(state, '#FFFFFF')
        self._cv_status_label.setStyleSheet(
            f'color: {colour}; background: rgba(0,0,0,150); '
            f'padding: 2px 8px; font: bold 11px monospace; border-radius: 3px;')
        self._cv_status_label.setText(f'CV: {state}  {confidence:.2f}')
        self._cv_status_label.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap is not None:
            self._display_pixmap(self._pixmap)
        if hasattr(self, '_btn_bar'):
            self._btn_bar.adjustSize()
            self._btn_bar.move(self.width() - self._btn_bar.width() - 5, 5)
            self._btn_bar.raise_()
        if hasattr(self, '_pause_overlay'):
            ow = self._pause_overlay.width()
            oh = self._pause_overlay.height()
            self._pause_overlay.move((self.width() - ow) // 2,
                                     (self.height() - oh) // 2)

    # ------------------------------------------------------------------
    # Placeholder
    # ------------------------------------------------------------------

    def _get_assets_path(self):
        return os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..', 'assets'))

    def _set_placeholder(self):
        path = os.path.join(self._get_assets_path(), 'jaeger_icon.png')
        if os.path.exists(path):
            px = QPixmap(path)
            if not px.isNull():
                self._display_pixmap(px)
                return
        self._img_label.setPixmap(QPixmap())

    # ------------------------------------------------------------------
    # Core display helper — scale to current label size, preserve 16:9
    # ------------------------------------------------------------------

    def _display_pixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        scaled = pixmap.scaled(
            self._img_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._img_label.setPixmap(scaled)

    # ------------------------------------------------------------------
    # Public API — callbacks registered by fcp_app.py
    # ------------------------------------------------------------------

    def set_load_callback(self, callback) -> None:
        self._load_callback = callback

    def set_alert_callback(self, callback) -> None:
        self._alert_callback = callback

    # ------------------------------------------------------------------
    # Public API — start playing a video file
    # ------------------------------------------------------------------

    def play_video(self, video_path: str, fps: int = 30) -> None:
        self.stop_video()
        self._cap = cv2.VideoCapture(video_path)
        if not self._cap.isOpened():
            raise RuntimeError(f'Unable to open video file: {video_path}')
        self._running  = True
        self._delay_ms = max(int(1000 / fps), 1)
        self._frame_timer.start(self._delay_ms)

    # ------------------------------------------------------------------
    # Public API — start displaying frames from a CV engine
    # ------------------------------------------------------------------

    def play_cv_engine(self, engine) -> None:
        self.stop_video()
        self._cv_engine = engine
        engine.start()
        self._running  = True
        self._delay_ms = 33
        self._frame_timer.start(self._delay_ms)
        if self._tuning_panel is not None and not self._tuning_panel.isHidden():
            self._tuning_panel.set_engine(engine)

    # ------------------------------------------------------------------
    # Timer slot — read one frame and display it
    # ------------------------------------------------------------------

    def _grab_frame(self):
        if self._cv_engine is not None:
            if hasattr(self._cv_engine, 'is_paused') and self._cv_engine.is_paused():
                if not self._pause_overlay_shown:
                    self._pause_overlay.adjustSize()
                    ow = self._pause_overlay.width()
                    oh = self._pause_overlay.height()
                    self._pause_overlay.move((self.width() - ow) // 2,
                                             (self.height() - oh) // 2)
                    self._pause_overlay.show()
                    self._pause_overlay.raise_()
                    self._pause_overlay_shown = True
                return
            elif self._pause_overlay_shown:
                self._pause_overlay.hide()
                self._pause_overlay_shown = False

            frame = self._cv_engine.read_frame()
            if frame is None:
                return
        elif self._cap is not None:
            ret, frame = self._cap.read()
            if not ret:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                return
        else:
            return

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        img = QImage(frame.data, w, h, w * ch, QImage.Format.Format_RGB888)
        self._display_pixmap(QPixmap.fromImage(img))

    # ------------------------------------------------------------------
    # Public API — stop playback
    # ------------------------------------------------------------------

    def stop_video(self) -> None:
        self._pause_overlay.hide()
        self._pause_overlay_shown = False
        self._running = False
        self._frame_timer.stop()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if self._cv_engine is not None:
            self._cv_engine.stop()
            self._cv_engine = None
        self._set_placeholder()

    # ------------------------------------------------------------------
    # Public API — shutdown
    # ------------------------------------------------------------------

    def clear(self):
        self.stop_video()

    # ------------------------------------------------------------------
    # Private — button bar handlers
    # ------------------------------------------------------------------

    def _on_load_clicked(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select video', '',
            'Video (*.mp4 *.avi *.mov *.MP4 *.AVI *.MOV);;All files (*)',
        )
        if path and self._load_callback:
            self._load_callback(path)

    def _on_gear_clicked(self):
        from view.frames.cv_tuning_panel import CVTuningPanel
        if self._tuning_panel is not None and not self._tuning_panel.isHidden():
            self._tuning_panel.raise_()
            self._tuning_panel.activateWindow()
            return
        if self._cv_engine is None or getattr(self._cv_engine, '_cfg', None) is None:
            return
        self._tuning_panel = CVTuningPanel(
            self, engine=self._cv_engine, alert_cb=self._alert_callback)
        self._tuning_panel.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._tuning_panel.destroyed.connect(
            lambda: setattr(self, '_tuning_panel', None))
        self._tuning_panel.show()
