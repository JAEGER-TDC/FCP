import configparser
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QShowEvent
from view.frames import video_frame, map_frame, alert_frame, control_frame
from view.frames.analytics_frame import AnalyticsFrame

_SASH_SECTION = 'layout.sash'


class FCPView(QWidget):
    # Carries (delay_ms, callback). Auto-connection means: direct when emitted
    # from the main thread, queued (→ main thread) when emitted from a
    # background UDP/serial thread. This replaces Tkinter's after() dispatch.
    _deferred = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config_path: str | None = None
        self._deferred.connect(self._on_deferred)

    def _on_deferred(self, delay_ms: int, callback):
        if delay_ms == 0:
            callback()
        else:
            QTimer.singleShot(delay_ms, callback)

    def after(self, delay_ms: int, callback):
        self._deferred.emit(delay_ms, callback)

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def init_gui(self, config_path: str | None = None):
        self._config_path = config_path

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._v_splitter = QSplitter(Qt.Orientation.Vertical)
        outer.addWidget(self._v_splitter)

        self._top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._v_splitter.addWidget(self._top_splitter)
        self._v_splitter.setStretchFactor(0, 2)

        self._bot_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._v_splitter.addWidget(self._bot_splitter)
        self._v_splitter.setStretchFactor(1, 2)

        # Top row: video (left) | map (right)
        self.video_frame = video_frame.VideoFrame(self._top_splitter)
        self._top_splitter.addWidget(self.video_frame)
        self._top_splitter.setStretchFactor(0, 2)
        # CV engine started by CVLaunchDialog after mode selection — not auto-started here

        self.map_frame = map_frame.MapFrame(self._top_splitter)
        self._top_splitter.addWidget(self.map_frame)
        self._top_splitter.setStretchFactor(1, 2)

        # Bottom-left: controls (fixed height) stacked above alert log (expands)
        _left_bottom = QWidget()
        _left_layout = QVBoxLayout(_left_bottom)
        _left_layout.setContentsMargins(0, 0, 0, 0)
        _left_layout.setSpacing(0)

        self.control_frame = control_frame.ControlFrame(_left_bottom, controller=self.controller)
        _left_layout.addWidget(self.control_frame, 0)

        self.alert_frame = alert_frame.AlertFrame(_left_bottom)
        _left_layout.addWidget(self.alert_frame, 1)

        self._bot_splitter.addWidget(_left_bottom)
        self._bot_splitter.setStretchFactor(0, 3)

        self.analytics_frame = AnalyticsFrame(self._bot_splitter, db=self.controller.model.analytics_db)
        self._bot_splitter.addWidget(self.analytics_frame)
        self._bot_splitter.setStretchFactor(1, 2)

        self._restore_pending = bool(config_path)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        if self._restore_pending:
            self._restore_pending = False
            # Defer one event-loop cycle so the window manager has applied the
            # maximized geometry before we read splitter sizes.
            QTimer.singleShot(0, self._restore_layout)

    # ------------------------------------------------------------------
    # Layout persistence
    # ------------------------------------------------------------------

    def save_layout(self):
        if not self._config_path:
            return

        def _frac(splitter: QSplitter) -> float:
            sizes = splitter.sizes()
            total = sum(sizes)
            return sizes[0] / total if total > 0 else 0.5

        config = configparser.ConfigParser()
        config.read(self._config_path)
        if not config.has_section(_SASH_SECTION):
            config.add_section(_SASH_SECTION)
        config[_SASH_SECTION]['vertical']       = f'{_frac(self._v_splitter):.4f}'
        config[_SASH_SECTION]['top_horizontal'] = f'{_frac(self._top_splitter):.4f}'
        config[_SASH_SECTION]['bot_horizontal'] = f'{_frac(self._bot_splitter):.4f}'
        with open(self._config_path, 'w') as f:
            config.write(f)

    def _restore_layout(self):
        config = configparser.ConfigParser()
        config.read(self._config_path)
        if not config.has_section(_SASH_SECTION):
            return

        sect = config[_SASH_SECTION]
        v_frac   = sect.getfloat('vertical',       fallback=None)
        top_frac = sect.getfloat('top_horizontal', fallback=None)
        bot_frac = sect.getfloat('bot_horizontal', fallback=None)

        def _apply(splitter: QSplitter, frac: float | None):
            if frac is None:
                return
            total = sum(splitter.sizes())
            if total > 10:
                a = int(frac * total)
                splitter.setSizes([a, total - a])

        _apply(self._v_splitter,   v_frac)
        _apply(self._top_splitter, top_frac)
        _apply(self._bot_splitter, bot_frac)

    # ------------------------------------------------------------------

    def set_controller(self, controller):
        self.controller = controller
