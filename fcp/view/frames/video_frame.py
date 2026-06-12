import os
import queue
import threading
import cv2
import numpy as np
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QWidget,
    QPushButton, QFrame, QGridLayout,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap, QFont, QColor
from view.frames.base_frame import BaseFrame

ASPECT = 16 / 9

# ── Right-panel constants ──────────────────────────────────────────────────
_PANEL_W       = 215        # fixed width of the HUD+scope column (px)
_SCOPE_PX      = 200        # scope display size — fixed square (px)
_ZOOM_LEVELS   = [1.5, 2.0, 3.0]  # available zoom levels (click to cycle)

# State → border colour (BGR for OpenCV drawing, then converted)
_STATE_COLOURS = {
    'LOCKED':     (0, 255, 0),
    'DARK LOCK':  (0, 140, 255),
    'PREDICTING': (0, 165, 255),
    'SEARCHING':  (100, 100, 100),
}
_STATE_QT_COLOURS = {
    'LOCKED':     '#00FF00',
    'DARK LOCK':  '#FF8C00',
    'PREDICTING': '#FFA500',
    'SEARCHING':  '#646464',
}

_BG   = '#F0F0F0'
_DIM  = '#757575'
_FG   = '#212121'
_MONO = 'font: 9pt Courier;'


class VideoFrame(BaseFrame):
    """Video feed (left) + HUD table and scope panel (right)."""

    _PAD = 8

    def __init__(self, parent=None):
        self._cap                 = None
        self._cv_engine           = None
        self._running             = False
        self._delay_ms            = 33
        self._pixmap              = None
        self._load_callback       = None
        self._alert_callback      = None
        self._config_path         = None
        self._tuning_panel        = None
        self._pause_overlay_shown = False
        self._scope_zoom          = 2.0   # current zoom level (cycles through _ZOOM_LEVELS)
        self._recording           = False
        self._video_writer        = None
        self._rec_queue:  queue.Queue = queue.Queue(maxsize=30)
        self._rec_thread: threading.Thread | None = None

        super().__init__(parent)

        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._grab_frame)

        self._scope_timer = QTimer(self)
        self._scope_timer.timeout.connect(self._update_scope_from_engine)
        self._scope_timer.start(100)   # 10fps scope refresh — decoupled from video

        self._set_placeholder()

    # ------------------------------------------------------------------
    # Widget construction
    # ------------------------------------------------------------------

    def create_widgets(self):
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(200, 150)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left: video label ──────────────────────────────────────────
        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._img_label.setMinimumSize(1, 1)
        self._img_label.setStyleSheet(f'background:{_BG};')
        root.addWidget(self._img_label, stretch=1)

        # ── Right: HUD + scope column ──────────────────────────────────
        self._right_panel = QWidget()
        self._right_panel.setFixedWidth(_PANEL_W)
        self._right_panel.setStyleSheet(f'background:{_BG};')
        right_vbox = QVBoxLayout(self._right_panel)
        right_vbox.setContentsMargins(6, 6, 6, 6)
        right_vbox.setSpacing(6)

        # Buttons row (Load Video + gear) at top of right panel
        btn_row = QWidget()
        _bl = QHBoxLayout(btn_row)
        _bl.setContentsMargins(0, 0, 0, 0)
        _bl.setSpacing(4)
        self._load_btn = QPushButton('Load Video')
        self._load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_btn.setStyleSheet(
            'background:#FFFFFF; color:#212121; border:1px solid #CCCCCC;'
            ' padding:2px 4px; font:bold 8pt Helvetica;')
        self._load_btn.clicked.connect(self._on_load_clicked)
        self._gear_btn = QPushButton('⚙')
        self._gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gear_btn.setStyleSheet(
            'background:#FFFFFF; color:#1565C0; border:1px solid #CCCCCC;'
            ' padding:2px 4px; font:11pt Helvetica;')
        self._gear_btn.clicked.connect(self._on_gear_clicked)
        _bl.addWidget(self._load_btn, stretch=1)
        _bl.addWidget(self._gear_btn)
        right_vbox.addWidget(btn_row)

        # Record button — only shown in live camera mode
        self._record_btn = QPushButton('⏺  Record')
        self._record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._record_btn.setStyleSheet(
            'background:#FFFFFF; color:#C62828; border:1px solid #CCCCCC;'
            ' padding:3px 4px; font:bold 8pt Helvetica;')
        self._record_btn.clicked.connect(self._toggle_recording)
        self._record_btn.setVisible(False)   # hidden until camera mode selected
        right_vbox.addWidget(self._record_btn)

        # ── HUD table ──────────────────────────────────────────────────
        self._hud_widget = QWidget()
        self._hud_widget.setStyleSheet(
            f'background:#FFFFFF; border:1px solid #CCCCCC; border-radius:3px;')
        hud_grid = QGridLayout(self._hud_widget)
        hud_grid.setContentsMargins(8, 8, 8, 8)
        hud_grid.setVerticalSpacing(4)
        hud_grid.setHorizontalSpacing(8)
        hud_grid.setColumnStretch(1, 1)

        self._hud_vals: dict[str, QLabel] = {}
        hud_rows = [
            ('STATE',  '---'),
            ('CONF',   '---'),
            ('FPS',    '---'),
            ('PEAK',   '---'),
            ('SPEED',  '---'),
            ('GIMBAL', '---'),
            ('LOST',   '---'),
            ('FRAME',  '---'),
        ]
        for i, (key, default) in enumerate(hud_rows):
            key_lbl = QLabel(key + ':')
            key_lbl.setStyleSheet(f'color:{_DIM}; {_MONO}')
            val_lbl = QLabel(default)
            val_lbl.setStyleSheet(f'color:{_FG}; {_MONO}')
            hud_grid.addWidget(key_lbl, i, 0, Qt.AlignmentFlag.AlignRight)
            hud_grid.addWidget(val_lbl, i, 1, Qt.AlignmentFlag.AlignLeft)
            self._hud_vals[key] = val_lbl

        right_vbox.addWidget(self._hud_widget)

        # ── Separator ──────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet('color:#30363d;')
        right_vbox.addWidget(sep)

        # ── Scope label ────────────────────────────────────────────────
        # Scope header row: label left, zoom toggle right
        scope_hdr_row = QWidget()
        scope_hdr_lay = QHBoxLayout(scope_hdr_row)
        scope_hdr_lay.setContentsMargins(0, 0, 0, 0)
        scope_hdr_lay.setSpacing(4)
        _scope_title = QLabel('SCOPE')
        _scope_title.setStyleSheet(f'color:{_DIM}; font:7pt Courier;')
        self._zoom_btn = QPushButton(f'{self._scope_zoom:.1f}x')
        self._zoom_btn.setFixedSize(38, 18)
        self._zoom_btn.setStyleSheet(
            f'background:#FFFFFF; color:#1565C0; border:1px solid #CCCCCC;'
            f' font:7pt Courier; padding:0px;')
        self._zoom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._zoom_btn.setToolTip('Click to cycle zoom level')
        self._zoom_btn.clicked.connect(self._cycle_zoom)
        scope_hdr_lay.addWidget(_scope_title)
        scope_hdr_lay.addStretch()
        scope_hdr_lay.addWidget(self._zoom_btn)
        right_vbox.addWidget(scope_hdr_row)

        self._scope_label = QLabel()
        self._scope_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scope_label.setFixedSize(_SCOPE_PX, _SCOPE_PX)   # always square
        self._scope_label.setStyleSheet(f'background:#E8E8E8; border:2px solid #CCCCCC;')
        right_vbox.addWidget(self._scope_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        root.addWidget(self._right_panel)

        # ── Pause overlay (floats over the whole VideoFrame) ───────────
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
    # Public API — HUD data update (called by controller every 100ms)
    # ------------------------------------------------------------------

    def update_hud_data(self, meta: dict) -> None:
        state  = meta.get('state', '---')
        col    = _STATE_QT_COLOURS.get(state, _FG)
        conf   = meta.get('confidence', 0.0)
        fps    = meta.get('fps', 0.0)
        peak   = meta.get('peak_ms', 0.0)
        speed  = meta.get('speed', 0.0)
        gimbal = meta.get('gimbal_err_px', 0.0)
        cx     = meta.get('cx', 0)
        cy     = meta.get('cy', 0)
        lost   = meta.get('lost_frames', 0)
        frame  = meta.get('frame_num', 0)

        self._hud_vals['STATE'].setText(state)
        self._hud_vals['STATE'].setStyleSheet(f'color:{col}; font:bold 9pt Courier;')
        self._hud_vals['CONF'].setText(f'{conf:.3f}')
        self._hud_vals['FPS'].setText(f'{fps:.0f}')
        peak_col = '#FF4040' if peak > 40 else _FG
        self._hud_vals['PEAK'].setText(f'{peak:.0f} ms')
        self._hud_vals['PEAK'].setStyleSheet(f'color:{peak_col}; {_MONO}')
        self._hud_vals['SPEED'].setText(f'{speed:.1f} px/f')
        self._hud_vals['GIMBAL'].setText(f'{gimbal:.0f} px')
        self._hud_vals['LOST'].setText(f'{lost}')
        self._hud_vals['FRAME'].setText(f'{frame}')

    # ------------------------------------------------------------------
    # Public API — CV status (no-op — state shown in HUD table)
    # ------------------------------------------------------------------

    def update_cv_status(self, state: str, confidence: float) -> None:
        pass

    # ------------------------------------------------------------------
    # Scope rendering
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Recording (raw camera feed, no overlays)
    # ------------------------------------------------------------------

    def _toggle_recording(self) -> None:
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        if self._cv_engine is None:
            return
        meta = self._cv_engine.get_metadata()
        w, h = meta.get('frame_w', 640), meta.get('frame_h', 480)
        if w == 0 or h == 0:
            return
        import datetime as _dt
        rec_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'recordings')
        os.makedirs(rec_dir, exist_ok=True)
        ts   = _dt.datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.abspath(os.path.join(rec_dir, f'raw_{ts}.mp4'))
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self._video_writer = cv2.VideoWriter(path, fourcc, 15.0, (w, h))
        if not self._video_writer.isOpened():
            self._video_writer = None
            return
        # Background thread drains the write queue so disk I/O never blocks Qt
        self._rec_thread = threading.Thread(target=self._rec_writer_loop,
                                            daemon=True, name='Recorder')
        self._rec_thread.start()
        self._recording = True
        self._record_btn.setText('⏹  Stop')
        self._record_btn.setStyleSheet(
            'background:#C62828; color:white; border:1px solid #8B0000;'
            ' padding:3px 4px; font:bold 8pt Helvetica;')
        print(f'[Record] started → {path}  ({w}x{h} @15fps, no overlays)')

    def _stop_recording(self) -> None:
        if not self._recording:
            return
        self._recording = False
        self._rec_queue.put(None)        # sentinel — tells writer thread to stop
        if self._rec_thread is not None:
            self._rec_thread.join(timeout=3.0)
            self._rec_thread = None
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
        self._record_btn.setText('⏺  Record')
        self._record_btn.setStyleSheet(
            'background:#FFFFFF; color:#C62828; border:1px solid #CCCCCC;'
            ' padding:3px 4px; font:bold 8pt Helvetica;')
        print('[Record] stopped')

    def _rec_writer_loop(self) -> None:
        """Background thread: drains _rec_queue and writes frames to disk."""
        while True:
            frame = self._rec_queue.get()
            if frame is None:            # sentinel
                break
            if self._video_writer is not None:
                self._video_writer.write(frame)

    def _cycle_zoom(self) -> None:
        idx = _ZOOM_LEVELS.index(self._scope_zoom) if self._scope_zoom in _ZOOM_LEVELS else 0
        self._scope_zoom = _ZOOM_LEVELS[(idx + 1) % len(_ZOOM_LEVELS)]
        self._zoom_btn.setText(f'{self._scope_zoom:.1f}x')

    def update_scope(self, raw_frame, cx: int, cy: int, state: str) -> None:
        if raw_frame is None:
            return
        h, w = raw_frame.shape[:2]
        if state == 'SEARCHING' or cx == 0:
            cx, cy = w // 2, h // 2

        # Compute crop radius from current zoom level
        radius = max(4, int(_SCOPE_PX / (2 * self._scope_zoom)))

        x0 = max(0, cx - radius);  x1 = min(w, cx + radius)
        y0 = max(0, cy - radius);  y1 = min(h, cy + radius)
        if x1 <= x0 or y1 <= y0:
            return

        lw = lh = _SCOPE_PX   # always square

        crop  = raw_frame[y0:y1, x0:x1]
        scope = cv2.resize(crop, (lw, lh), interpolation=cv2.INTER_LINEAR)

        # Crosshair
        ic_x, ic_y = lw // 2, lh // 2
        cv2.line(scope, (ic_x - 16, ic_y), (ic_x + 16, ic_y), (0, 255, 255), 1, cv2.LINE_AA)
        cv2.line(scope, (ic_x, ic_y - 16), (ic_x, ic_y + 16), (0, 255, 255), 1, cv2.LINE_AA)
        cv2.circle(scope, (ic_x, ic_y), 8, (0, 0, 255), 1, cv2.LINE_AA)

        # Colored border
        border_bgr = _STATE_COLOURS.get(state, (100, 100, 100))
        cv2.rectangle(scope, (1, 1), (lw - 2, lh - 2), border_bgr, 2)

        scope_rgb = cv2.cvtColor(scope, cv2.COLOR_BGR2RGB)
        img = QImage(scope_rgb.data, lw, lh, lw * 3, QImage.Format.Format_RGB888)
        self._scope_label.setPixmap(QPixmap.fromImage(img))

    def _update_scope_from_engine(self) -> None:
        if self._cv_engine is None:
            return
        raw  = self._cv_engine.get_raw_frame()
        meta = self._cv_engine.get_metadata()
        self.update_scope(raw, meta.get('cx', 0), meta.get('cy', 0),
                          meta.get('state', 'SEARCHING'))

    # ------------------------------------------------------------------
    # Resize
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap is not None:
            self._display_pixmap(self._pixmap)
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
    # Core display — scale to label size, preserve aspect ratio
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
    # Public API — callbacks
    # ------------------------------------------------------------------

    def set_load_callback(self, callback) -> None:
        self._load_callback = callback

    def set_alert_callback(self, callback) -> None:
        self._alert_callback = callback

    def set_config_path(self, path: str) -> None:
        self._config_path = path

    # ------------------------------------------------------------------
    # Public API — video / engine control
    # ------------------------------------------------------------------

    def play_video(self, video_path: str, fps: int = 30) -> None:
        self.stop_video()
        self._cap = cv2.VideoCapture(video_path)
        if not self._cap.isOpened():
            raise RuntimeError(f'Unable to open video file: {video_path}')
        self._running  = True
        self._delay_ms = max(int(1000 / fps), 1)
        self._frame_timer.start(self._delay_ms)

    def play_cv_engine(self, engine) -> None:
        self.stop_video()
        self._cv_engine = engine
        engine.start()
        self._running  = True
        is_camera = getattr(getattr(engine, '_cfg', None), 'USE_LIVE_CAMERA', False)
        self._delay_ms = 33
        self._frame_timer.start(self._delay_ms)
        if self._tuning_panel is not None and not self._tuning_panel.isHidden():
            self._tuning_panel.set_engine(engine)
        self._load_btn.setVisible(not is_camera)
        self._record_btn.setVisible(is_camera)

    # ------------------------------------------------------------------
    # Timer slot
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

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch  = frame_rgb.shape
        img = QImage(frame_rgb.data, w, h, w * ch, QImage.Format.Format_RGB888)
        self._display_pixmap(QPixmap.fromImage(img))

        # Enqueue raw frame for background recording (non-blocking)
        if self._recording and self._cv_engine is not None:
            raw = self._cv_engine.get_raw_frame()
            if raw is not None:
                try:
                    self._rec_queue.put_nowait(raw.copy())
                except queue.Full:
                    pass   # drop frame rather than block Qt

    # ------------------------------------------------------------------
    # Stop / clear
    # ------------------------------------------------------------------

    def stop_video(self) -> None:
        self._stop_recording()
        self._load_btn.setVisible(True)
        self._record_btn.setVisible(False)
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

    def clear(self):
        self.stop_video()

    # ------------------------------------------------------------------
    # Button handlers
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
            self, engine=self._cv_engine, alert_cb=self._alert_callback,
            config_path=self._config_path)
        self._tuning_panel.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._tuning_panel.destroyed.connect(
            lambda: setattr(self, '_tuning_panel', None))
        self._tuning_panel.show()
