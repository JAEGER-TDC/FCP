from view.frames.base_frame import BaseFrame
from PyQt6.QtWidgets import QVBoxLayout, QTextEdit
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from datetime import datetime
from view import theme

INFO    = 'INFO'
WARNING = 'WARNING'
ERROR   = 'ERROR'

_COLORS = {
    INFO:    QColor(theme.ALERT_INFO),
    WARNING: QColor(theme.ALERT_WARNING),
    ERROR:   QColor(theme.ALERT_ERROR),
}

class AlertFrame(BaseFrame):
    def create_widgets(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._alert_text = QTextEdit()
        self._alert_text.setReadOnly(True)
        layout.addWidget(self._alert_text)

    #===================================================================

    def add_alert(self, alert_message: str, severity: str = INFO):
        timestamp = datetime.now().strftime('%H:%M:%S')
        line = f'[{timestamp}] [{severity}] {alert_message}\n'

        fmt = QTextCharFormat()
        fmt.setForeground(_COLORS.get(severity, _COLORS[INFO]))

        cursor = self._alert_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(line, fmt)
        self._alert_text.ensureCursorVisible()
