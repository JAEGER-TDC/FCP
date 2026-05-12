import tkinter as tk
from tkinter import ttk

class DNESimTargetingFrame(ttk.LabelFrame):
    """Displays the last targeting packet received from FCP."""

    def __init__(self, parent):
        super().__init__(parent, text='Last Received Targeting Data')
        self.az = tk.DoubleVar(value=0.0)
        self.el = tk.DoubleVar(value=0.0)
        self.range_m = tk.DoubleVar(value=0.0)
        self.az_rate = tk.DoubleVar(value=0.0)
        self.el_rate = tk.DoubleVar(value=0.0)
        self.range_rate = tk.DoubleVar(value=0.0)
        self.fire = tk.IntVar(value=0)
        self.state_command = tk.IntVar(value=0)
        self.create_widgets()

    def create_widgets(self):
        fields = [
            ('Azimuth (°):', self.az),
            ('Elevation (°):', self.el),
            ('Range (m):', self.range_m),
            ('Az Rate (°/s):', self.az_rate),
            ('El Rate (°/s):', self.el_rate),
            ('Range Rate (m/s):', self.range_rate),
            ('Fire:', self.fire),
            ('State Command:', self.state_command),
        ]
        for row, (label, var) in enumerate(fields):
            ttk.Label(self, text=label).grid(row=row, column=0, padx=10, pady=4, sticky='e')
            ttk.Label(self, textvariable=var).grid(row=row, column=1, padx=10, pady=4, sticky='w')

    #===================================================================

    def update_targeting(self, az, el, range_m, az_rate, el_rate, range_rate, fire, state_command):
        self.az.set(round(az, 2))
        self.el.set(round(el, 2))
        self.range_m.set(round(range_m, 2))
        self.az_rate.set(round(az_rate, 2))
        self.el_rate.set(round(el_rate, 2))
        self.range_rate.set(round(range_rate, 2))
        self.fire.set(fire)
        self.state_command.set(state_command)
