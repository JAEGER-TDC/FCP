from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton
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
        # Set before super().__init__() so create_widgets() can reference it.
        self.controller = controller
        super().__init__(parent)

        # QTimer requires a valid QObject parent, so created after super().__init__().
        self._grace_timer = QTimer(self)
        self._grace_timer.setSingleShot(True)
        self._grace_timer.timeout.connect(self._grace_period_expired)

    #===================================================================

    def create_widgets(self):
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(10, 10, 10, 10)

        # --- Detection Modes -----------------------------------------
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

        # --- Engage / Stop button ------------------------------------
        engage_font = QFont(theme.FONT_FAMILY, theme.FONT_SIZE_LARGE)
        engage_font.setBold(True)
        self.engage_button = QPushButton('Engage')
        self.engage_button.setFont(engage_font)
        self.engage_button.clicked.connect(self._on_button_clicked)
        self._apply_inactive_style()
        vbox.addWidget(self.engage_button)

    #===================================================================

    @staticmethod
    def _make_sensor_btn(label: str) -> QPushButton:
        btn = QPushButton(f'{label} Enabled')
        btn.setCheckable(True)
        btn.setChecked(True)
        btn.setStyleSheet(f'background-color: {theme.SENSOR_ENABLED_BG};')
        return btn

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
        """Called by controller when the engaged-RAT set gains or loses members."""
        if active == self._engagement_active:
            return
        self._engagement_active = active
        if active:
            self._cancel_grace_period()
            self._apply_stop_style()
        else:
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
