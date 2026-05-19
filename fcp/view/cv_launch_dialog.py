"""
CVLaunchDialog — startup mode selection shown once when JAEGER launches.
Presents 3 mutually exclusive CV operating modes.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QSpinBox,
)
from PyQt6.QtCore import Qt

# Match the application's light theme (view/theme.py)
_BG   = '#F0F0F0'
_CARD = '#FFFFFF'
_FG   = '#212121'
_DIM  = '#616161'
_DIV  = '#E0E0E0'


def _card_ss(accent: str) -> str:
    return (
        f'QPushButton {{ background:{_CARD}; color:{accent};'
        f' border:1px solid {_DIV}; border-radius:4px;'
        f' padding:14px 16px; text-align:left; font-size:10pt; }}'
        f' QPushButton:hover {{ border:1px solid {accent}; }}'
    )


class CVLaunchDialog(QDialog):
    """Modal startup dialog — user must pick a CV mode before the mission begins."""

    def __init__(self, parent, controller):
        super().__init__(parent)
        self._controller = controller
        self.setWindowTitle('JAEGER — Select Operating Mode')
        self.setModal(True)
        self.setFixedSize(480, 340)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setStyleSheet(f'QDialog {{ background:{_BG}; }} QLabel {{ color:{_FG}; }}')
        self._build_ui()

    def _make_card(self, icon: str, title: str, subtitle: str,
                   accent: str, callback) -> QPushButton:
        btn = QPushButton(f'{icon}  {title}\n{subtitle}')
        btn.setStyleSheet(_card_ss(accent))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(callback)
        return btn

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(4)

        hdr = QLabel('JAEGER  TURBODRONE  C2')
        hdr.setStyleSheet(f'color:{_FG}; font:bold 13pt Helvetica;')
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(hdr)

        sub = QLabel('Choose a CV operating mode to begin the mission')
        sub.setStyleSheet(f'color:{_DIM}; font:9pt Helvetica;')
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(sub)

        root.addSpacing(10)

        # Icons use standard unicode symbols — emoji glyphs are unreliable on Linux
        root.addWidget(self._make_card(
            '▶', 'Simulator',
            'Scripted tracking on test video — runs on any machine, no GPU required',
            '#388E3C', self._pick_simulator,
        ))
        root.addWidget(self._make_card(
            '→', 'Load Video  +  Real CV',
            'Browse for a video file and run the TensorRT tracking engine',
            '#1565C0', self._pick_video,
        ))
        root.addWidget(self._make_card(
            '◎', 'USB Camera  +  Real CV',
            'Live webcam feed processed by the TensorRT tracking engine',
            '#F57F17', self._pick_camera,
        ))

        # Camera index row — shown below the USB card
        _cam_row = QHBoxLayout()
        _cam_lbl = QLabel('Camera index:')
        _cam_lbl.setStyleSheet(f'color:{_DIM}; font:9pt Helvetica;')
        self._cam_spin = QSpinBox()
        self._cam_spin.setRange(0, 9)
        self._cam_spin.setValue(0)   # USB camera attached via usbipd appears as /dev/video0
        self._cam_spin.setFixedWidth(54)
        self._cam_spin.setStyleSheet(
            f'background:{_CARD}; color:{_FG}; border:1px solid {_DIV}; border-radius:3px;')
        _cam_hint = QLabel('(0 = built-in, 1 = first USB)')
        _cam_hint.setStyleSheet(f'color:{_DIM}; font:8pt Helvetica;')
        _cam_row.addSpacing(8)
        _cam_row.addWidget(_cam_lbl)
        _cam_row.addWidget(self._cam_spin)
        _cam_row.addWidget(_cam_hint)
        _cam_row.addStretch()
        root.addLayout(_cam_row)

        self._status = QLabel('')
        self._status.setStyleSheet('color:#C62828; font:9pt Helvetica;')
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._status)

    # ── Handlers ──────────────────────────────────────────────────────────

    def _pick_simulator(self):
        self._controller.start_mode_simulator()
        self.accept()

    def _pick_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select video file for CV tracking', '',
            'Video files (*.mp4 *.avi *.mov *.MP4 *.AVI *.MOV);;All files (*)',
        )
        if not path:
            return
        self._status.setText('Starting CV engine…')
        self._controller.start_mode_video(path)
        self.accept()

    def _pick_camera(self):
        self._status.setText('Opening camera…')
        self._controller.start_mode_camera(camera_index=self._cam_spin.value())
        self.accept()
