from PyQt6.QtWidgets import QGroupBox, QGridLayout, QLabel
from PyQt6.QtCore import Qt

class NodeFrame(QGroupBox):
    def __init__(self, parent=None, node_title=''):
        super().__init__(node_title, parent)

        self._battery_val = QLabel('0.0')
        self._temp_val    = QLabel('0.0')
        self._error_val   = QLabel('0')
        self._status_val  = QLabel('')
        self._status_val.setMinimumWidth(120)

        layout = QGridLayout(self)
        layout.addWidget(QLabel('Battery Percentage:'), 0, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._battery_val,             0, 1, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(QLabel('Temperature (°C):'),   1, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._temp_val,                1, 1, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(QLabel('Error Code:'),         2, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._error_val,               2, 1, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(QLabel('Status Flag:'),        3, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._status_val,              3, 1, Qt.AlignmentFlag.AlignLeft)

    def update_node_data(self, node):
        self._battery_val.setText(str(node.battery_percent))
        self._temp_val.setText(str(node.temperature_c))
        self._error_val.setText(str(node.error_code))
        self._status_val.setText(node.status_flag)