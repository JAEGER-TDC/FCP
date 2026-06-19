import sys
import os

from PyQt6.QtWidgets import QApplication, QMainWindow, QLineEdit, QTextEdit
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon

from model.fcp_model import FCPModel
from view.fcp_view import FCPView
from controller.fcp_controller import FCPController
import view.theme as theme
from view.cv_launch_dialog import CVLaunchDialog


class FCPApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('JAEGER Forward Command Post')
        self.resize(1280, 720)

        icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'jaeger_logo.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._model = FCPModel()
        self._model.analytics_db.start_mission()

        # Log the initial enabled state of all three sensors at mission start
        db = self._model.analytics_db
        for sensor in ('lidar', 'rf', 'acoustic'):
            db.log_sensor_event(sensor, 'enabled')

        self._view = FCPView(self)
        self.setCentralWidget(self._view)

        self._controller = FCPController(self._model, self._view)
        self._view.set_controller(self._controller)
        _config_path = os.path.join(os.path.dirname(__file__), 'cfg', 'config.ini')
        self._view.init_gui(config_path=_config_path)

        self._view.video_frame.set_load_callback(self._controller.load_video)
        self._view.video_frame.set_alert_callback(self._view.alert_frame.add_alert)
        self._controller.start_connections()
        QTimer.singleShot(100, self._show_cv_dialog)

        # Do an initial analytics refresh so tables populate immediately
        self._view.analytics_frame.refresh()

    def _show_cv_dialog(self):
        CVLaunchDialog(self, self._controller).exec()

    def keyPressEvent(self, event):
        focused = QApplication.focusWidget()
        if isinstance(focused, (QLineEdit, QTextEdit)):
            return super().keyPressEvent(event)
        k = event.key()
        if k == Qt.Key.Key_Space:
            self._controller.cv_pause_toggle()
        elif k == Qt.Key.Key_R:
            self._controller.cv_reset_tracking()
        elif k == Qt.Key.Key_S:
            self._controller.cv_screenshot()
        elif k == Qt.Key.Key_V:
            self._controller.cv_restart_video()
        elif k == Qt.Key.Key_Q:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._view.save_layout()
        self._model.analytics_db.end_mission()
        self._model.analytics_db.close()
        super().closeEvent(event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    theme.apply(app)
    window = FCPApp()
    window.showMaximized()
    sys.exit(app.exec())
