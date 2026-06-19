from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton,
    QLabel, QCheckBox, QGridLayout, QProgressBar,
)
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from view.frames.base_frame import BaseFrame
from view import theme


class ControlFrame(BaseFrame):
    def __init__(self, parent=None, controller=None):
        self.lidar_enabled    = True
        self.rf_enabled       = True
        self.acoustic_enabled = True
        self._any_in_zone3    = False
        self._engagement_active = False
        self.controller = controller
        super().__init__(parent)

        self._grace_timer = QTimer(self)
        self._grace_timer.setSingleShot(True)
        self._grace_timer.timeout.connect(self._grace_period_expired)

        # Tick the "last packet age" display every 500ms
        self._age_timer = QTimer(self)
        self._age_timer.setInterval(500)
        self._age_timer.timeout.connect(self._refresh_packet_age)
        self._age_timer.start()
        self._last_packet_time: float | None = None

    #===================================================================

    def create_widgets(self):
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(4)

        # ── Detection Modes ──────────────────────────────────────────
        modes_group = QGroupBox('Detection Modes')
        modes_hbox = QHBoxLayout(modes_group)

        self._lidar_btn    = self._make_sensor_btn('LiDAR')
        self._rf_btn       = self._make_sensor_btn('RF')
        self._acoustic_btn = self._make_sensor_btn('Acoustic')

        self._lidar_btn.toggled.connect(self._on_lidar_toggled)
        self._rf_btn.toggled.connect(self._on_rf_toggled)
        self._acoustic_btn.toggled.connect(self._on_acoustic_toggled)

        modes_hbox.addWidget(self._lidar_btn)
        modes_hbox.addWidget(self._rf_btn)
        modes_hbox.addWidget(self._acoustic_btn)
        vbox.addWidget(modes_group)

        # ── Engage / Stop button ─────────────────────────────────────
        engage_font = QFont(theme.FONT_FAMILY, theme.FONT_SIZE_LARGE)
        engage_font.setBold(True)
        self.engage_button = QPushButton('Engage')
        self.engage_button.setFont(engage_font)
        self.engage_button.clicked.connect(self._on_button_clicked)
        self._apply_inactive_style()
        vbox.addWidget(self.engage_button)

        # ── Settings row: port config + audio toggle ─────────────────
        settings_row = QHBoxLayout()
        self._port_btn = QPushButton('Serial Ports…')
        self._port_btn.setToolTip('Configure DNN / DNE serial port assignment')
        self._port_btn.clicked.connect(self._open_port_dialog)
        self._audio_chk = QCheckBox('Audio')
        self._audio_chk.setChecked(True)
        self._audio_chk.toggled.connect(self._on_audio_toggled)
        self._dne_aim_chk = QCheckBox('Show DNE Aim')
        self._dne_aim_chk.setChecked(False)
        self._dne_aim_chk.setToolTip('Show DNE targeting reticle on the zone map')
        self._dne_aim_chk.toggled.connect(self._on_dne_aim_toggled)
        settings_row.addWidget(self._port_btn)
        settings_row.addStretch()
        settings_row.addWidget(self._audio_chk)
        settings_row.addWidget(self._dne_aim_chk)
        vbox.addLayout(settings_row)

        # ── Dwell Timer ──────────────────────────────────────────────
        self._dwell_group = QGroupBox('Engage Dwell')
        dwell_layout = QVBoxLayout(self._dwell_group)
        dwell_layout.setSpacing(3)
        dwell_layout.setContentsMargins(8, 4, 8, 6)

        status_row = QHBoxLayout()
        self._dwell_engaged_lbl = QLabel('Engaged: —')
        self._dwell_time_lbl = QLabel('On Target: 0.0 / 3.0s')
        status_row.addWidget(self._dwell_engaged_lbl)
        status_row.addStretch()
        status_row.addWidget(self._dwell_time_lbl)
        dwell_layout.addLayout(status_row)

        self._dwell_bar = QProgressBar()
        self._dwell_bar.setRange(0, 300)   # tenths of a second × 10 (3.0s = 300)
        self._dwell_bar.setValue(0)
        self._dwell_bar.setTextVisible(False)
        self._dwell_bar.setFixedHeight(14)
        self._dwell_bar.setStyleSheet(
            'QProgressBar { border: 1px solid #bbb; border-radius: 3px; background: #eee; }'
            'QProgressBar::chunk { background: #4caf50; border-radius: 2px; }'
        )
        dwell_layout.addWidget(self._dwell_bar)

        self._dwell_group.setVisible(False)   # hidden until engagement starts
        vbox.addWidget(self._dwell_group)

        # ── DNE Last Packet (+ Manual Test, same box to save vertical space) ──
        pkt_group = QGroupBox('DNE Last Packet')
        pkt_vbox = QVBoxLayout(pkt_group)
        pkt_vbox.setSpacing(4)
        pkt_vbox.setContentsMargins(8, 4, 8, 6)

        pkt_grid = QGridLayout()
        pkt_grid.setVerticalSpacing(2)
        pkt_grid.setHorizontalSpacing(8)

        self._pkt_az    = self._pkt_val('—')
        self._pkt_el    = self._pkt_val('—')
        self._pkt_range = self._pkt_val('—')
        self._pkt_laser = self._pkt_val('—')
        self._pkt_state = self._pkt_val('—')
        self._pkt_age   = self._pkt_val('—')

        for col, (lbl, widget) in enumerate([
            ('Az',    self._pkt_az),
            ('El',    self._pkt_el),
            ('Range', self._pkt_range),
        ]):
            pkt_grid.addWidget(QLabel(lbl + ':'), 0, col * 2)
            pkt_grid.addWidget(widget,            0, col * 2 + 1)

        for col, (lbl, widget) in enumerate([
            ('Laser', self._pkt_laser),
            ('State', self._pkt_state),
            ('Age',   self._pkt_age),
        ]):
            pkt_grid.addWidget(QLabel(lbl + ':'), 1, col * 2)
            pkt_grid.addWidget(widget,            1, col * 2 + 1)

        pkt_vbox.addLayout(pkt_grid)

        # ── Manual DNE Test (bench/field test without DNN connected) ──
        test_row = QHBoxLayout()
        test_row.addWidget(QLabel('Manual Test:'))
        self._test_laser_btn = QPushButton('Test Laser: OFF')
        self._test_laser_btn.setCheckable(True)
        self._test_laser_btn.setToolTip(
            'Fires the DNE laser directly with az=el=range=0, bypassing\n'
            'engagement/dwell logic entirely. Works with no DNN connected —\n'
            'use to bench-test the DNE link before the detector is online.')
        self._test_laser_btn.setStyleSheet('background-color: #ccc;')
        self._test_laser_btn.toggled.connect(self._on_test_laser_toggled)
        test_row.addWidget(self._test_laser_btn, 1)
        pkt_vbox.addLayout(test_row)

        vbox.addWidget(pkt_group)

    #===================================================================
    # Helpers
    #===================================================================

    @staticmethod
    def _make_sensor_btn(label: str) -> QPushButton:
        btn = QPushButton(f'{label} Enabled')
        btn.setCheckable(True)
        btn.setChecked(True)
        btn.setStyleSheet(f'background-color: {theme.SENSOR_ENABLED_BG};')
        return btn

    @staticmethod
    def _pkt_val(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet('font-family: monospace;')
        return lbl

    def _open_port_dialog(self):
        from view.frames.port_dialog import PortAssignmentDialog
        PortAssignmentDialog(self.window(), self.controller).exec()

    def _on_audio_toggled(self, checked: bool):
        if self.controller:
            self.controller.audio_enabled = checked

    def _on_dne_aim_toggled(self, checked: bool):
        from view.frames.map_frame import MapFrame
        map_frame = self.window().findChild(MapFrame)
        if map_frame:
            map_frame.set_dne_aim_visible(checked)

    def _on_test_laser_toggled(self, checked: bool):
        self._test_laser_btn.setText(f'Test Laser: {"ON" if checked else "OFF"}')
        self._test_laser_btn.setStyleSheet(
            'background-color: #f44336; color: white;' if checked else 'background-color: #ccc;')
        if self.controller:
            self.controller.test_dne_laser(checked)

    #===================================================================
    # Sensor toggles
    #===================================================================

    def _on_lidar_toggled(self, checked: bool):
        self.lidar_enabled = checked
        self._lidar_btn.setText('LiDAR Enabled' if checked else 'LiDAR Disabled')
        self._lidar_btn.setStyleSheet(
            f'background-color: {theme.SENSOR_ENABLED_BG if checked else theme.SENSOR_DISABLED_BG};')
        self.controller.set_lidar_enabled(checked)

    def _on_rf_toggled(self, checked: bool):
        self.rf_enabled = checked
        self._rf_btn.setText('RF Enabled' if checked else 'RF Disabled')
        self._rf_btn.setStyleSheet(
            f'background-color: {theme.SENSOR_ENABLED_BG if checked else theme.SENSOR_DISABLED_BG};')
        self.controller.set_rf_enabled(checked)

    def _on_acoustic_toggled(self, checked: bool):
        self.acoustic_enabled = checked
        self._acoustic_btn.setText('Acoustic Enabled' if checked else 'Acoustic Disabled')
        self._acoustic_btn.setStyleSheet(
            f'background-color: {theme.SENSOR_ENABLED_BG if checked else theme.SENSOR_DISABLED_BG};')
        self.controller.set_acoustic_enabled(checked)

    #===================================================================
    # Dwell timer
    #===================================================================

    def update_dwell_display(self, engaged_secs: float | None,
                             on_target_secs: float, dwell_goal: float):
        """Update the dwell timer panel.

        engaged_secs  — wall-clock seconds since Engage was pressed (None = not engaged)
        on_target_secs — accumulated crosshair-on-drone seconds for the current burst
        dwell_goal     — seconds required for a kill confirm (e.g. 3.0)
        """
        if engaged_secs is None:
            self._dwell_group.setVisible(False)
            self._dwell_bar.setValue(0)
            return

        self._dwell_group.setVisible(True)
        self._dwell_engaged_lbl.setText(f'Engaged: {engaged_secs:.1f}s')

        self._dwell_time_lbl.setText(f'On Target: {on_target_secs:.1f} / {dwell_goal:.1f}s')
        bar_val = int(on_target_secs / dwell_goal * 300)
        self._dwell_bar.setValue(min(bar_val, 300))

        # Bar color: green → yellow → red as it fills
        frac = on_target_secs / dwell_goal
        if frac < 0.5:
            chunk_color = '#4caf50'   # green
        elif frac < 0.85:
            chunk_color = '#ff9800'   # orange
        else:
            chunk_color = '#f44336'   # red
        self._dwell_bar.setStyleSheet(
            'QProgressBar { border: 1px solid #bbb; border-radius: 3px; background: #eee; }'
            f'QProgressBar::chunk {{ background: {chunk_color}; border-radius: 2px; }}'
        )

    #===================================================================
    # DNE packet readout
    #===================================================================

    def update_dne_packet(self, az: float, el: float, range_m: float,
                          fire: int, state: int):
        import time
        self._last_packet_time = time.monotonic()
        self._pkt_az.setText(f'{az:+.2f}°')
        self._pkt_el.setText(f'{el:+.2f}°')
        self._pkt_range.setText(f'{range_m:.1f}m')
        laser_on = bool(fire)
        self._pkt_laser.setText('ON' if laser_on else 'OFF')
        self._pkt_laser.setStyleSheet(
            f'font-family: monospace; color: {"red" if laser_on else "gray"};')
        state_lbl = {1: 'TRACK', 2: 'ENGAGE'}.get(state, str(state))
        self._pkt_state.setText(state_lbl)
        self._pkt_state.setStyleSheet(
            f'font-family: monospace; color: {"red" if state == 2 else "black"};')
        self._pkt_age.setText('0.0s')

    def _refresh_packet_age(self):
        import time
        if self._last_packet_time is None:
            return
        age = time.monotonic() - self._last_packet_time
        self._pkt_age.setText(f'{age:.1f}s')
        self._pkt_age.setStyleSheet(
            f'font-family: monospace; color: {"red" if age > 2.0 else "black"};')

    #===================================================================
    # Engage button state machine
    #===================================================================

    def update_engage_state(self, any_in_zone3: bool):
        if any_in_zone3 == self._any_in_zone3:
            return
        prev = self._any_in_zone3
        self._any_in_zone3 = any_in_zone3
        if any_in_zone3:
            self._cancel_grace_period()
            self._apply_active_style()
        elif prev:
            self._start_grace_period()

    def _apply_active_style(self):
        self.engage_button.setEnabled(True)
        self.engage_button.setText('Engage')
        self.engage_button.setStyleSheet(
            f'background-color: {theme.ENGAGE_BG_ACTIVE}; color: {theme.ENGAGE_FG_ACTIVE};'
            f'padding: {theme.ENGAGE_PAD_Y}px {theme.ENGAGE_PAD_X}px;')

    def _apply_inactive_style(self):
        self.engage_button.setEnabled(False)
        self.engage_button.setText('Engage')
        self.engage_button.setStyleSheet(
            f'background-color: {theme.ENGAGE_BG_INACTIVE}; color: {theme.ENGAGE_FG_INACTIVE};'
            f'padding: {theme.ENGAGE_PAD_Y}px {theme.ENGAGE_PAD_X}px;')

    def _apply_stop_style(self):
        self.engage_button.setEnabled(True)
        self.engage_button.setText('Stop')
        self.engage_button.setStyleSheet(
            f'background-color: {theme.ENGAGE_BG_STOP}; color: {theme.ENGAGE_FG_STOP};'
            f'padding: {theme.ENGAGE_PAD_Y}px {theme.ENGAGE_PAD_X}px;')

    def _start_grace_period(self):
        self._cancel_grace_period()
        self._apply_active_style()
        self._grace_timer.start(theme.ENGAGE_GRACE_MS)

    def _grace_period_expired(self):
        self.controller.cancel_pending_engagement()
        self._apply_inactive_style()

    def _cancel_grace_period(self):
        self._grace_timer.stop()

    #===================================================================

    def update_engagement_active(self, active: bool):
        if active == self._engagement_active:
            return
        self._engagement_active = active
        # A real engagement takes priority over the bench test — don't let both
        # fight over the laser/state-command fields in the same DNE packet.
        self._test_laser_btn.setEnabled(not active)
        if active and self._test_laser_btn.isChecked():
            self._test_laser_btn.setChecked(False)
        if active:
            self._cancel_grace_period()
            self._apply_stop_style()
        else:
            self._dwell_group.setVisible(False)
            self._dwell_bar.setValue(0)
            if self._any_in_zone3 or self._grace_timer.isActive():
                self._apply_active_style()
            else:
                self._apply_inactive_style()

    #===================================================================

    def _on_button_clicked(self):
        if self._engagement_active:
            self._on_stop()
        else:
            self._on_engage()

    def _on_stop(self):
        self.controller.stop_engagement()

    def _on_engage(self):
        self.controller.engage_primary_target()
