"""
CVLaunchDialog — startup mode selection shown once when JAEGER launches.
Presents 3 mutually exclusive CV operating modes.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QFileDialog, QWidget,
)
from PyQt6.QtCore import Qt

_BG   = '#0d1117'
_CARD = '#161b22'
_FG   = '#e0e0e0'
_DIM  = '#8b949e'
_ACC  = '#7ec8e3'


def _card_ss(accent: str) -> str:
    return (
        f'QPushButton {{ background:{_CARD}; color:{accent};'
        f' border:1px solid #30363d; border-radius:4px;'
        f' padding:14px 16px; text-align:left; font-size:10pt; }}'
        f' QPushButton:hover {{ border-color:{accent}; }}'
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
        self.setStyleSheet(f'background:{_BG};')
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
        hdr.setStyleSheet(f'color:{_ACC}; font:bold 13pt Helvetica;')
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(hdr)

        sub = QLabel('Choose a CV operating mode to begin the mission')
        sub.setStyleSheet(f'color:{_DIM}; font:9pt Helvetica;')
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(sub)

        root.addSpacing(10)

        root.addWidget(self._make_card(
            '▶', 'Simulator',
            'Scripted tracking on test video — runs on any machine, no GPU required',
            '#4CAF50', self._pick_simulator,
        ))
        root.addWidget(self._make_card(
            '📂', 'Load Video  +  Real CV',
            'Browse for a video file and run the TensorRT tracking engine',
            _ACC, self._pick_video,
        ))
        root.addWidget(self._make_card(
            '📷', 'USB Camera  +  Real CV',
            'Live webcam feed processed by the TensorRT tracking engine',
            '#b39ddb', self._pick_camera,
        ))

        self._status = QLabel('')
        self._status.setStyleSheet('color:#e57373; font:9pt Helvetica;')
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
        self._controller.start_mode_camera()
        self.accept()
