"""
port_dialog.py — Serial port assignment dialog.

Lets the operator pick which /dev/ttyACM* (or /dev/pts/* for socat tests)
maps to the DNN detector and the DNE effector, then reconnects live.
"""

import glob
import serial.tools.list_ports

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QComboBox, QPushButton, QLabel,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor


def _available_ports() -> list[str]:
    """Return sorted list of serial port devices visible to the OS."""
    hw  = sorted(p.device for p in serial.tools.list_ports.comports())
    pts = sorted(glob.glob('/dev/pts/[0-9]*'))          # socat virtual ports
    tcp = ['socket://127.0.0.1:6000']                   # DNE simulator TCP
    return hw + pts + tcp


class PortAssignmentDialog(QDialog):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle('Serial Port Assignment')
        self.setModal(True)
        self.setMinimumWidth(460)
        self._build_ui()
        self._refresh_ports()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── Port selectors ─────────────────────────────────────────────
        port_group = QGroupBox('Device Port Assignment')
        form = QFormLayout(port_group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._dnn_combo = QComboBox()
        self._dnn_combo.setEditable(True)
        self._dne_combo = QComboBox()
        self._dne_combo.setEditable(True)
        self._dne_combo.setToolTip(
            'Hardware: /dev/ttyACM1\n'
            'DNE simulator (TCP): socket://127.0.0.1:6000')
        form.addRow('DNN  (Detector / Raspberry Pi):', self._dnn_combo)
        form.addRow('DNE  (Effector):', self._dne_combo)
        root.addWidget(port_group)

        # ── Connection status ──────────────────────────────────────────
        status_group = QGroupBox('Connection Status')
        status_layout = QVBoxLayout(status_group)
        self._dnn_status_lbl = QLabel()
        self._dne_status_lbl = QLabel()
        status_layout.addWidget(self._dnn_status_lbl)
        status_layout.addWidget(self._dne_status_lbl)
        root.addWidget(status_group)

        self._update_status_labels()

        # ── Buttons ────────────────────────────────────────────────────
        # ── Sim-mode shortcut ──────────────────────────────────────────
        sim_group = QGroupBox('Simulator Mode (no hardware)')
        sim_layout = QHBoxLayout(sim_group)
        sim_info = QLabel(
            'DNN sim → UDP auto-detected on port 5000\n'
            'DNE sim → TCP on socket://127.0.0.1:6000')
        sim_info.setStyleSheet('color: #555;')
        sim_btn = QPushButton('Use Simulator Connections')
        sim_btn.clicked.connect(self._apply_sim_mode)
        sim_layout.addWidget(sim_info, 1)
        sim_layout.addWidget(sim_btn)
        root.addWidget(sim_group)

        # ── Buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        refresh_btn = QPushButton('Refresh Ports')
        refresh_btn.clicked.connect(self._refresh_ports)

        self._dnn_only_btn = QPushButton('Reconnect DNN')
        self._dnn_only_btn.clicked.connect(self._reconnect_dnn)

        self._dne_only_btn = QPushButton('Reconnect DNE')
        self._dne_only_btn.clicked.connect(self._reconnect_dne)

        apply_btn = QPushButton('Apply Both && Reconnect')
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._apply_both)

        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.accept)

        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._dnn_only_btn)
        btn_row.addWidget(self._dne_only_btn)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_ports(self):
        ports = _available_ports()
        for combo, attr in ((self._dnn_combo, 'dnn_serial_port'),
                            (self._dne_combo, 'dne_port')):
            current = combo.currentText() or getattr(self.controller, attr, '')
            combo.clear()
            combo.addItems(ports)
            idx = combo.findText(current)
            combo.setCurrentIndex(max(idx, 0))

    def _update_status_labels(self):
        dnn_serial_ok = self.controller._dnn_ser is not None
        dnn_udp_ok    = getattr(self.controller, '_dnn_udp_active', False)
        dne_ok        = self.controller._ser is not None

        if dnn_serial_ok:
            dnn_text  = f'DNN:  ● Connected  ({self.controller.dnn_serial_port})'
            dnn_color = 'green'
        elif dnn_udp_ok:
            import configparser as _cp
            _port = self.controller.config.getint('DNN.recv.connection', 'port', fallback=5000)
            dnn_text  = f'DNN:  ● UDP fallback  (0.0.0.0:{_port})'
            dnn_color = '#d07000'   # amber — connected but not serial
        else:
            dnn_text  = f'DNN:  ○ Disconnected  ({self.controller.dnn_serial_port})'
            dnn_color = 'red'

        self._dnn_status_lbl.setText(dnn_text)
        self._dnn_status_lbl.setStyleSheet(f'color: {dnn_color};')
        self._dne_status_lbl.setText(
            f'DNE:  {"● Connected  " if dne_ok else "○ Disconnected"}  '
            f'({self.controller.dne_port})')
        self._dne_status_lbl.setStyleSheet(
            f'color: {"green" if dne_ok else "red"};')

    def _reconnect_dnn(self):
        port = self._dnn_combo.currentText()
        if port:
            self.controller.reconnect_serial(dnn_port=port)
            self._update_status_labels()

    def _reconnect_dne(self):
        port = self._dne_combo.currentText()
        if port:
            self.controller.reconnect_serial(dne_port=port)
            self._update_status_labels()

    def _apply_both(self):
        dnn = self._dnn_combo.currentText()
        dne = self._dne_combo.currentText()
        self.controller.reconnect_serial(dnn_port=dnn or None, dne_port=dne or None)
        self._update_status_labels()

    def _apply_sim_mode(self):
        """Connect DNE to the local simulator TCP server.  DNN falls back to UDP automatically."""
        self.controller.reconnect_serial(dne_port='socket://127.0.0.1:6000')
        self._update_status_labels()
