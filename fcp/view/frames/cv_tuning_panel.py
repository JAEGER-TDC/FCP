"""
CVTuningPanel — floating window for live CV engine parameter tuning.
Opened by the gear button on the video frame.
"""

from PyQt6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QCheckBox, QDoubleSpinBox, QSpinBox,
    QScrollArea, QGroupBox, QGridLayout, QSizePolicy,
)
from PyQt6.QtCore import Qt

_BG    = '#1a1a2e'
_FG    = '#e0e0e0'
_SECH  = '#7ec8e3'
_ENTRY = '#16213e'
_DIM   = '#555566'

_LABEL_SS = f'color:{_FG}; font-size:9pt;'
_HINT_SS  = f'color:{_DIM}; font-size:8pt; font-style:italic;'
_GB_SS    = (f'QGroupBox {{ color:{_SECH}; font-size:9pt; font-weight:bold;'
             f' border:1px solid #30363d; border-radius:4px; margin-top:6px; padding-top:4px; }}'
             f' QGroupBox::title {{ subcontrol-origin:margin; left:8px; }}')
_SB_SS    = (f'QDoubleSpinBox, QSpinBox {{ background:{_ENTRY}; color:{_FG};'
             f' border:1px solid #30363d; padding:1px 4px; font:9pt Courier; }}'
             f' QDoubleSpinBox::up-button, QSpinBox::up-button,'
             f' QDoubleSpinBox::down-button, QSpinBox::down-button'
             f' {{ background:#0f3460; width:16px; }}')
_CB_SS    = f'QCheckBox {{ color:{_FG}; font-size:9pt; }} QCheckBox::indicator {{ width:13px; height:13px; }}'

_LABELS: dict = {
    'CONF_ACQUIRE':           ('Conf Acquire',      '{:.3f}'),
    'CONF_HOLD':              ('Conf Hold',          '{:.3f}'),
    'CONF_HINT':              ('Conf Hint',          '{:.3f}'),
    'KALMAN_ENABLED':         ('Kalman Filter',),
    'max_lost_frames':        ('Max Lost Frames',    '{}'),
    'ENGAGE_RADIUS_PX':       ('Engage Radius',      '{} px'),
    'DARK_SEARCH_ENABLED':    ('Dark Search',),
    'DARK_COLOR_CHECK':       ('Sky Color Ring',),
    'DARK_PIXEL_RATIO':       ('Dark Pixel Ratio',   '{:.2f}'),
    'DARK_MIN_AREA':          ('Min Blob Area',      '{} px²'),
    'DARK_MAX_AREA':          ('Max Blob Area',      '{} px²'),
    'DARK_SEARCH_RADIUS':     ('Search Radius',      '{} px'),
    'DARK_GRACE_FRAMES':      ('Grace Frames',       '{}'),
    'DARK_LOCK_CONF_TIMEOUT': ('Conf Timeout',       '{} frames'),
    'oef_min_cutoff':         ('OEF Min Cutoff',     '{:.4f}'),
    'oef_beta':               ('OEF Beta',           '{:.5f}'),
    'SHOW_HUD_PANEL':         ('HUD Panel',),
    'SHOW_FPS':               ('FPS Counter',),
    'SHOW_CROSSHAIR':         ('Crosshair',),
    'SHOW_LOCK_RING':         ('Lock Ring',),
    'SHOW_LASER_CENTER':      ('Laser Center',),
    'SHOW_OFFSET_LINE':       ('Offset Line',),
    'SHOW_GIMBAL_ERROR':      ('Gimbal Error',),
    'SHOW_TRAIL':             ('Position Trail',),
    'SHOW_ZOOM_INSET':        ('Zoom Inset',),
    'SHOW_VELOCITY_ARROW':    ('Velocity Arrow',),
    'SHOW_DARK_BLOBS':        ('Dark Blobs',),
}


def _format_alert(attr: str, value) -> str:
    entry = _LABELS.get(attr)
    if entry is None:
        return f'CV tuning: {attr} = {value}'
    name = entry[0]
    if len(entry) == 1:
        return f"CV: {'Enabled' if value else 'Disabled'} {name}"
    return f'CV: {name} → {entry[1].format(value)}'


def _scroll_wrap(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(inner)
    sa.setStyleSheet(f'QScrollArea {{ background:{_BG}; border:none; }}'
                     f' QScrollBar:vertical {{ background:{_ENTRY}; width:8px; }}'
                     f' QScrollBar::handle:vertical {{ background:#30363d; }}')
    return sa


class CVTuningPanel(QDialog):
    """Live-tuning panel for CVEngine/CVEngineSimulator config fields."""

    def __init__(self, parent, engine, alert_cb=None):
        super().__init__(parent)
        self._engine   = engine
        self._alert_cb = alert_cb
        self._controls: dict[str, QWidget] = {}

        self.setWindowTitle('CV Engine Tuning')
        self.setModal(False)
        self.resize(360, 520)
        self.setStyleSheet(f'QDialog {{ background:{_BG}; }} QLabel {{ color:{_FG}; }}')
        self._build_ui()
        self.raise_()

    # ── Engine swap ───────────────────────────────────────────────────────

    def set_engine(self, engine) -> None:
        self._engine = engine
        self._refresh_values()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _cfg(self):
        return getattr(self._engine, '_cfg', None)

    def _update(self, attr: str, value) -> None:
        if self._engine is None:
            return
        if hasattr(self._engine, 'update_config'):
            self._engine.update_config(attr, value)
        else:
            cfg = self._cfg()
            if cfg is not None:
                setattr(cfg, attr, value)
        if self._alert_cb is not None:
            self._alert_cb(_format_alert(attr, value))

    def _make_dsb(self, attr: str, min_: float, max_: float,
                  decimals: int, step: float) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setDecimals(decimals)
        sb.setSingleStep(step)
        sb.setRange(min_, max_)
        cfg = self._cfg()
        sb.setValue(float(getattr(cfg, attr, min_)) if cfg else min_)
        sb.setStyleSheet(_SB_SS)
        sb.setFixedWidth(110)
        sb.valueChanged.connect(lambda v, a=attr: self._update(a, v))
        self._controls[attr] = sb
        return sb

    def _make_sb(self, attr: str, min_: int, max_: int, step: int = 1) -> QSpinBox:
        sb = QSpinBox()
        sb.setSingleStep(step)
        sb.setRange(min_, max_)
        cfg = self._cfg()
        sb.setValue(int(getattr(cfg, attr, min_)) if cfg else min_)
        sb.setStyleSheet(_SB_SS)
        sb.setFixedWidth(110)
        sb.valueChanged.connect(lambda v, a=attr: self._update(a, v))
        self._controls[attr] = sb
        return sb

    def _make_check(self, attr: str, label: str) -> QCheckBox:
        cb = QCheckBox(label)
        cfg = self._cfg()
        cb.setChecked(bool(getattr(cfg, attr, False)) if cfg else False)
        cb.setStyleSheet(_CB_SS)
        cb.toggled.connect(lambda v, a=attr: self._update(a, v))
        self._controls[attr] = cb
        return cb

    def _hint(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_HINT_SS)
        lbl.setWordWrap(True)
        return lbl

    def _gb(self, title: str) -> tuple[QGroupBox, QFormLayout]:
        gb = QGroupBox(title)
        gb.setStyleSheet(_GB_SS)
        fl = QFormLayout(gb)
        fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        fl.setSpacing(4)
        fl.setContentsMargins(8, 12, 8, 6)
        return gb, fl

    def _row(self, fl: QFormLayout, label: str, widget: QWidget):
        lbl = QLabel(label)
        lbl.setStyleSheet(_LABEL_SS)
        fl.addRow(lbl, widget)

    # ── UI build ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        nb = QTabWidget()
        nb.setStyleSheet(
            f'QTabWidget::pane {{ background:{_BG}; border:1px solid #30363d; }}'
            f' QTabBar::tab {{ background:#0f3460; color:{_FG}; padding:4px 12px; font-size:9pt; }}'
            f' QTabBar::tab:selected {{ background:{_BG}; color:{_SECH}; }}'
        )
        root.addWidget(nb)

        nb.addTab(_scroll_wrap(self._build_tracking_tab()), 'Tracking')
        nb.addTab(_scroll_wrap(self._build_dark_search_tab()), 'Dark Search')
        nb.addTab(_scroll_wrap(self._build_display_tab()), 'Display')

    def _build_tracking_tab(self) -> QWidget:
        outer = QWidget()
        outer.setStyleSheet(f'background:{_BG};')
        vbox = QVBoxLayout(outer)
        vbox.setSpacing(8)
        vbox.setContentsMargins(8, 8, 8, 8)

        gb, fl = self._gb('Confidence Thresholds')
        self._row(fl, 'Acquire', self._make_dsb('CONF_ACQUIRE', 0.05, 0.50, 3, 0.01))
        self._row(fl, 'Hold',    self._make_dsb('CONF_HOLD',    0.02, 0.20, 3, 0.005))
        self._row(fl, 'Hint',    self._make_dsb('CONF_HINT',    0.01, 0.10, 3, 0.005))
        fl.addRow(self._hint('Acquire: lock-on threshold  |  Hold: stay-locked threshold'))
        vbox.addWidget(gb)

        gb2, fl2 = self._gb('Kalman Filter (PREDICTING mode)')
        fl2.addRow(self._make_check('KALMAN_ENABLED', 'Enabled'))
        self._row(fl2, 'Max lost frames', self._make_sb('max_lost_frames', 5, 300, 5))
        vbox.addWidget(gb2)

        gb3, fl3 = self._gb('Engagement')
        self._row(fl3, 'Lock radius (px)', self._make_sb('ENGAGE_RADIUS_PX', 10, 120, 5))
        fl3.addRow(self._hint('Gimbal error must be < this for on_target=True'))
        vbox.addWidget(gb3)

        vbox.addStretch(1)
        return outer

    def _build_dark_search_tab(self) -> QWidget:
        outer = QWidget()
        outer.setStyleSheet(f'background:{_BG};')
        vbox = QVBoxLayout(outer)
        vbox.setSpacing(8)
        vbox.setContentsMargins(8, 8, 8, 8)

        gb, fl = self._gb('Dark-Pixel Search')
        fl.addRow(self._make_check('DARK_SEARCH_ENABLED', 'Enabled'))
        fl.addRow(self._make_check('DARK_COLOR_CHECK', 'Blue-sky color ring filter (disable if overcast)'))
        self._row(fl, 'Pixel ratio',    self._make_dsb('DARK_PIXEL_RATIO', 0.30, 0.80, 2, 0.01))
        fl.addRow(self._hint('Blob < sky × ratio  |  lower = only very dark blobs'))
        self._row(fl, 'Min area (px²)', self._make_sb('DARK_MIN_AREA', 10, 10000, 50))
        fl.addRow(self._hint('∸30ft drone ≈ 500–3000px²   ≈100ft ≈ 30–150px²'))
        self._row(fl, 'Max area (px²)', self._make_sb('DARK_MAX_AREA', 1000, 100000, 500))
        self._row(fl, 'Search radius',  self._make_sb('DARK_SEARCH_RADIUS', 50, 600, 10))
        fl.addRow(self._hint('Raise for fast-moving drones'))
        self._row(fl, 'Grace frames',   self._make_sb('DARK_GRACE_FRAMES', 2, 30, 1))
        fl.addRow(self._hint('Hold DARK LOCK through brief misses'))
        self._row(fl, 'Conf timeout',   self._make_sb('DARK_LOCK_CONF_TIMEOUT', 5, 60, 1))
        fl.addRow(self._hint('Release false-lock if CV gives no signal'))
        vbox.addWidget(gb)

        vbox.addStretch(1)
        return outer

    def _build_display_tab(self) -> QWidget:
        outer = QWidget()
        outer.setStyleSheet(f'background:{_BG};')
        vbox = QVBoxLayout(outer)
        vbox.setSpacing(8)
        vbox.setContentsMargins(8, 8, 8, 8)

        gb, fl = self._gb('Position Smoothing (One-Euro Filter)')
        self._row(fl, 'Min cutoff', self._make_dsb('oef_min_cutoff', 0.01, 0.20, 4, 0.005))
        self._row(fl, 'Beta',       self._make_dsb('oef_beta', 0.0001, 0.01, 5, 0.0001))
        fl.addRow(self._hint('Smoothing resets the filter — brief jump is normal'))
        vbox.addWidget(gb)

        gb2 = QGroupBox('HUD Overlays')
        gb2.setStyleSheet(_GB_SS)
        grid = QGridLayout(gb2)
        grid.setSpacing(4)
        grid.setContentsMargins(8, 12, 8, 6)
        toggles = [
            ('SHOW_HUD_PANEL',      'HUD info panel'),
            ('SHOW_FPS',            'FPS counter'),
            ('SHOW_CROSSHAIR',      'Crosshair on drone'),
            ('SHOW_LOCK_RING',      'Lock ring'),
            ('SHOW_LASER_CENTER',   'Laser center marker'),
            ('SHOW_OFFSET_LINE',    'Laser→drone line'),
            ('SHOW_GIMBAL_ERROR',   'Gimbal error text'),
            ('SHOW_TRAIL',          'Position trail'),
            ('SHOW_ZOOM_INSET',     'Zoom inset'),
            ('SHOW_VELOCITY_ARROW', 'Velocity arrow'),
            ('SHOW_DARK_BLOBS',     'Dark blob candidates'),
        ]
        for i, (attr, lbl) in enumerate(toggles):
            grid.addWidget(self._make_check(attr, lbl), i // 2, i % 2)
        vbox.addWidget(gb2)

        vbox.addStretch(1)
        return outer

    # ── Refresh all controls from current engine config ───────────────────

    def _refresh_values(self):
        cfg = self._cfg()
        if cfg is None:
            return
        for attr, widget in self._controls.items():
            val = getattr(cfg, attr, None)
            if val is None:
                continue
            widget.blockSignals(True)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(val))
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(val))
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(val))
            widget.blockSignals(False)
