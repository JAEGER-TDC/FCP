from PyQt6.QtWidgets import QWidget

class BaseFrame(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.create_widgets()

    def create_widgets(self):
        pass