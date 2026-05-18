"""
CVTuningPanel — floating window for live CV engine parameter tuning.
Opened by the gear button on the video frame.
"""

import configparser

from PyQt6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QCheckBox, QDoubleSpinBox, QSpinBox,
    QScrollArea, QGroupBox, QGridLayout, QSizePolicy, QPushButton,
)
from PyQt6.QtCore import Qt

# Light mode — readable in direct sunlight outdoors
_BG    = '#F0F0F0'
_FG    = '#212121'
_SECH  = '#1565C0'
_ENTRY = '#FFFFFF'
_DIM   = '#757575'
_DIV   = '#CCCCCC'

_LABEL_SS = f'color:{_FG}; font-size:9pt;'
_HINT_SS  = f'color:{_DIM}; font-size:8pt; font-style:italic;'
_GB_SS    = (f'QGroupBox {{ color:{_SECH}; font-size:9pt; font-weight:bold;'
             f' border:1px solid {_DIV}; border-radius:4px; margin-top:8px; padding-top:6px; }}'
             f' QGroupBox::title {{ subcontrol-origin:margin; left:8px; }}')
_SB_SS    = (f'QDoubleSpinBox, QSpinBox {{ background:{_ENTRY}; color:{_FG};'
             f' border:1px solid {_DIV}; padding:2px 4px; font:9pt Courier; }}'
             f' QDoubleSpinBox::up-button, QSpinBox::up-button,'
             f' QDoubleSpinBox::down-button, QSpinBox::down-button'
             f' {{ background:#E3EEFF; width:16px; }}')
_CB_SS    = f'QCheckBox {{ color:{_FG}; font-size:9pt; }} QCheckBox::indicator {{ width:14px; height:14px; }}'

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

    def __init__(self, parent, engine, alert_cb=None, config_path=None):
        super().__init__(parent)
        self._engine      = engine
        self._alert_cb    = alert_cb
        self._config_path = config_path
        self._controls: dict[str, QWidget] = {}

        self.setWindowTitle('CV Engine Tuning')
        self.setModal(False)
        self.resize(370, 540)
        self.setStyleSheet(
            f'QDialog {{ background:{_BG}; }}'
            f' QLabel {{ color:{_FG}; }}'
            f' QPushButton {{ background:{_ENTRY}; color:{_FG}; border:1px solid {_DIV};'
            f'   padding:4px 10px; font:9pt; border-radius:3px; }}'
            f' QPushButton:hover {{ background:#E3EEFF; }}'
        )
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
        self._save_tuning()

    def _save_tuning(self) -> None:
        if not self._config_path:
            return
        cfg = self._cfg()
        if cfg is None:
            return
        parser = configparser.ConfigParser()
        parser.read(self._config_path)
        if not parser.has_section('cv.tuning'):
            parser.add_section('cv.tuning')
        for attr in _LABELS:
            val = getattr(cfg, attr, None)
            if val is not None:
                parser['cv.tuning'][attr.lower()] = str(val)
        with open(self._config_path, 'w') as f:
            parser.write(f)

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
            f'QTabWidget::pane {{ background:{_BG}; border:1px solid {_DIV}; }}'
            f' QTabBar::tab {{ background:#E3EEFF; color:{_FG}; padding:5px 14px; font-size:9pt; }}'
            f' QTabBar::tab:selected {{ background:{_BG}; color:{_SECH}; font-weight:bold; }}'
        )
        root.addWidget(nb)

        nb.addTab(_scroll_wrap(self._build_tracking_tab()), 'Tracking')
        nb.addTab(_scroll_wrap(self._build_dark_search_tab()), 'Dark Search')
        nb.addTab(_scroll_wrap(self._build_display_tab()), 'Display')

        # Restore Defaults button at the bottom
        _restore_btn = QPushButton('↺  Restore Defaults')
        _restore_btn.clicked.connect(self._restore_defaults)
        root.addWidget(_restore_btn)

    def _build_tracking_tab(self) -> QWidget:
        outer = QWidget()
        outer.setStyleSheet(f'background:{_BG};')
        vbox = QVBoxLayout(outer)
        vbox.setSpacing(10)
        vbox.setContentsMargins(10, 10, 10, 10)

        gb, fl = self._gb('Confidence Thresholds')
        self._row(fl, 'Acquire', self._make_dsb('CONF_ACQUIRE', 0.01, 0.99, 3, 0.01))
        self._row(fl, 'Hold',    self._make_dsb('CONF_HOLD',    0.01, 0.99, 3, 0.005))
        self._row(fl, 'Hint',    self._make_dsb('CONF_HINT',    0.001, 0.50, 3, 0.005))
        fl.addRow(self._hint('Acquire: lock-on threshold  |  Hold: stay-locked threshold'))
        vbox.addWidget(gb)

        gb2, fl2 = self._gb('Kalman Filter (PREDICTING mode)')
        fl2.addRow(self._make_check('KALMAN_ENABLED', 'Enabled'))
        self._row(fl2, 'Max lost frames', self._make_sb('max_lost_frames', 1, 1000, 5))
        vbox.addWidget(gb2)

        gb3, fl3 = self._gb('Engagement')
        self._row(fl3, 'Lock radius (px)', self._make_sb('ENGAGE_RADIUS_PX', 1, 500, 5))
        fl3.addRow(self._hint('Gimbal error must be < this for on_target=True'))
        vbox.addWidget(gb3)

        vbox.addStretch(1)
        return outer

    def _build_dark_search_tab(self) -> QWidget:
        outer = QWidget()
        outer.setStyleSheet(f'background:{_BG};')
        vbox = QVBoxLayout(outer)
        vbox.setSpacing(10)
        vbox.setContentsMargins(10, 10, 10, 10)

        gb, fl = self._gb('Dark-Pixel Search')
        fl.addRow(self._make_check('DARK_SEARCH_ENABLED', 'Enabled'))
        fl.addRow(self._make_check('DARK_COLOR_CHECK', 'Blue-sky color ring filter (disable if overcast)'))
        self._row(fl, 'Pixel ratio',    self._make_dsb('DARK_PIXEL_RATIO', 0.05, 1.00, 2, 0.01))
        fl.addRow(self._hint('Blob < sky × ratio  |  lower = only very dark blobs'))
        self._row(fl, 'Min area (px²)', self._make_sb('DARK_MIN_AREA', 1, 50000, 10))
        fl.addRow(self._hint('At 640×480: drone ≈ 50–500px²  |  At 1080p: 500–3000px²'))
        self._row(fl, 'Max area (px²)', self._make_sb('DARK_MAX_AREA', 100, 500000, 100))
        self._row(fl, 'Search radius',  self._make_sb('DARK_SEARCH_RADIUS', 10, 2000, 10))
        fl.addRow(self._hint('At 640×480 keep ≤200 to avoid background false-locks'))
        self._row(fl, 'Grace frames',   self._make_sb('DARK_GRACE_FRAMES', 0, 100, 1))
        fl.addRow(self._hint('Hold DARK LOCK through brief misses'))
        self._row(fl, 'Conf timeout',   self._make_sb('DARK_LOCK_CONF_TIMEOUT', 1, 200, 1))
        fl.addRow(self._hint('Release false-lock if CV gives no signal'))
        vbox.addWidget(gb)

        vbox.addStretch(1)
        return outer

    def _build_display_tab(self) -> QWidget:
        outer = QWidget()
        outer.setStyleSheet(f'background:{_BG};')
        vbox = QVBoxLayout(outer)
        vbox.setSpacing(10)
        vbox.setContentsMargins(10, 10, 10, 10)

        gb, fl = self._gb('Position Smoothing (One-Euro Filter)')
        self._row(fl, 'Min cutoff', self._make_dsb('oef_min_cutoff', 0.001, 2.0,  4, 0.005))
        self._row(fl, 'Beta',       self._make_dsb('oef_beta',       0.00001, 0.10, 5, 0.0001))
        fl.addRow(self._hint('Smoothing resets the filter — brief jump is normal'))
        vbox.addWidget(gb)

        gb2 = QGroupBox('HUD Overlays')
        gb2.setStyleSheet(_GB_SS)
        grid = QGridLayout(gb2)
        grid.setSpacing(6)
        grid.setContentsMargins(10, 14, 10, 8)
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

    def _restore_defaults(self) -> None:
        """Reset all tunable fields to factory defaults and save."""
        from cv.cv_draw import Config as _Cfg
        defaults = _Cfg()
        cfg = self._cfg()
        if cfg is None:
            return
        for attr in _LABELS:
            default_val = getattr(defaults, attr, None)
            if default_val is None:
                continue
            # Apply to live engine
            if hasattr(self._engine, 'update_config'):
                self._engine.update_config(attr, default_val)
            else:
                setattr(cfg, attr, default_val)
        # Refresh UI widgets to show new values
        self._refresh_values()
        # Persist to config.ini
        self._save_tuning()
