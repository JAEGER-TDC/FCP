import tkinter as tk
from tkinter import ttk

class DNESimStatusFrame(ttk.LabelFrame):
    """Displays DNE health/laser state with clickable toggle labels."""

    def __init__(self, parent, controller):
        super().__init__(parent, text='DNE Status')
        self.controller = controller
        self.am_i_healthy = True
        self.laser_firing = False
        self.create_widgets()

    def create_widgets(self):
        ttk.Label(self, text='am_i_healthy:').grid(row=0, column=0, padx=10, pady=8, sticky='e')
        self._healthy_label = tk.Label(self, text='ON', background='lightgreen',
                                       relief='raised', padx=8, pady=4)
        self._healthy_label.grid(row=0, column=1, padx=10, pady=8, sticky='w')
        self._healthy_label.bind('<Button-1>', lambda _: self._toggle_healthy())

        ttk.Label(self, text='laser_firing:').grid(row=1, column=0, padx=10, pady=8, sticky='e')
        self._laser_label = tk.Label(self, text='OFF', background='lightgray',
                                     relief='raised', padx=8, pady=4)
        self._laser_label.grid(row=1, column=1, padx=10, pady=8, sticky='w')
        self._laser_label.bind('<Button-1>', lambda _: self._toggle_laser())

    #===================================================================

    def _toggle_healthy(self):
        self.controller.set_healthy(not self.am_i_healthy)

    def _toggle_laser(self):
        self.controller.set_laser_firing(not self.laser_firing)

    #===================================================================

    def set_healthy(self, value: bool):
        self.am_i_healthy = value
        if value:
            self._healthy_label.configure(text='ON', background='lightgreen')
        else:
            self._healthy_label.configure(text='OFF', background='red', foreground='white')

    def set_laser_firing(self, value: bool):
        self.laser_firing = value
        if value:
            self._laser_label.configure(text='ON', background='red', foreground='white')
        else:
            self._laser_label.configure(text='OFF', background='lightgray', foreground='black')
