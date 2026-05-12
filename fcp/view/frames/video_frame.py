import os
import cv2
from PyQt6.QtWidgets import QVBoxLayout, QLabel, QSizePolicy
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from view.frames.base_frame import BaseFrame

ASPECT = 16 / 9


class VideoFrame(BaseFrame):
    """Shows a video stream (or static image) that always fills the panel."""
    _PAD = 8

    def __init__(self, parent=None):
        self._cap       = None   # cv2.VideoCapture instance
        self._cv_engine = None   # CVEngineBase instance (engine mode)
        self._running   = False
        self._delay_ms  = 33
        self._pixmap    = None   # latest QPixmap, kept for resize repaints

        super().__init__(parent)

        # Repeating timer — fires at a fixed interval, no chained single-shots.
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

    # ------------------------------------------------------------------
    # Resize — repaint cached pixmap at new label size, no frame re-read
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

    # ------------------------------------------------------------------
    # Placeholder
    # ------------------------------------------------------------------

    def _get_assets_path(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'assets'))

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
    # Public API — start playing a video file
    # ------------------------------------------------------------------

    def play_video(self, video_path: str, fps: int = 30) -> None:
        """Begin playback of *video_path* at *fps* frames per second."""
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
        """Switch the video panel to display annotated frames from a CVEngine."""
        self.stop_video()
        self._cv_engine = engine
        engine.start()
        self._running  = True
        self._delay_ms = 33    # ~30 fps
        self._frame_timer.start(self._delay_ms)

    # ------------------------------------------------------------------
    # Timer slot — read one frame and display it
    # ------------------------------------------------------------------

    def _grab_frame(self):
        if self._cv_engine is not None:
            frame = self._cv_engine.read_frame()
            if frame is None:
                return
        elif self._cap is not None:
            ret, frame = self._cap.read()
            if not ret:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # rewind pre-canned video
                return
        else:
            return

        # BGR → RGB directly into QImage — no PIL intermediary.
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        img = QImage(frame.data, w, h, w * ch, QImage.Format.Format_RGB888)
        # fromImage() deep-copies the pixel data so frame can go out of scope.
        self._display_pixmap(QPixmap.fromImage(img))

    # ------------------------------------------------------------------
    # Public API — stop playback
    # ------------------------------------------------------------------

    def stop_video(self) -> None:
        """Terminate playback and release resources."""
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
        """Called when the whole application is shutting down."""
        self.stop_video()
