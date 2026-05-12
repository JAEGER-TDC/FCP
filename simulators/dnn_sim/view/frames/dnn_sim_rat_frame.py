import tkinter as tk
from tkinter import ttk

class DNNSimRATFrame(ttk.LabelFrame):
    def __init__(self, parent, rat_id, controller):
        self.rat_id = rat_id
        super().__init__(parent, text=f'RAT {self.rat_id}')

        self.controller = controller

        self.is_simulating = False

        self.zone_value = tk.IntVar(value=0)
        self.az_value = tk.DoubleVar(value=0.0)
        self.el_value = tk.DoubleVar(value=0.0)
        self.range_value = tk.DoubleVar(value=0.0)
        self.az_rate = tk.DoubleVar(value=0.0)
        self.el_rate = tk.DoubleVar(value=0.0)
        self.range_rate = tk.DoubleVar(value=0.0)    

        self.create_widgets()

        self.columnconfigure(0, weight=1, uniform="subframe")
        self.columnconfigure(1, weight=1, uniform="subframe")

    #===================================================================

    def create_widgets(self):
        self.sim_button = ttk.Button(self, text='Start Simulation', command=self.start_simulation)
        self.sim_button.grid(row=0, column=0, columnspan=2, padx=5, pady=5)

        self.zone_label = ttk.Label(self, text='Zone:')
        self.zone_label.grid(row=1, column=0, padx=5, pady=5, sticky='e')

        self.zone_value_label = ttk.Label(self, textvariable=self.zone_value)
        self.zone_value_label.grid(row=1, column=1, padx=5, pady=5, sticky='w')

        self.az_label = ttk.Label(self, text='Azimuth:')
        self.az_label.grid(row=2, column=0, padx=5, pady=5, sticky='e')

        self.az_value_label = ttk.Label(self, textvariable=self.az_value)
        self.az_value_label.grid(row=2, column=1, padx=5, pady=5, sticky='w')

        self.el_label = ttk.Label(self, text='Elevation:')
        self.el_label.grid(row=3, column=0, padx=5, pady=5, sticky='e')

        self.el_value_label = ttk.Label(self, textvariable=self.el_value)
        self.el_value_label.grid(row=3, column=1, padx=5, pady=5, sticky='w')

        self.range_label = ttk.Label(self, text='Range:')
        self.range_label.grid(row=4, column=0, padx=5, pady=5, sticky='e')

        self.range_value_label = ttk.Label(self, textvariable=self.range_value)
        self.range_value_label.grid(row=4, column=1, padx=5, pady=5, sticky='w')

        self.az_rate_label = ttk.Label(self, text='Azimuth Rate:')
        self.az_rate_label.grid(row=5, column=0, padx=5, pady=5, sticky='e')

        self.az_rate_value_label = ttk.Label(self, textvariable=self.az_rate)
        self.az_rate_value_label.grid(row=5, column=1, padx=5, pady=5, sticky='w')

        self.el_rate_label = ttk.Label(self, text='Elevation Rate:')
        self.el_rate_label.grid(row=6, column=0, padx=5, pady=5, sticky='e')

        self.el_rate_value_label = ttk.Label(self, textvariable=self.el_rate)
        self.el_rate_value_label.grid(row=6, column=1, padx=5, pady=5, sticky='w')

        self.range_rate_label = ttk.Label(self, text='Range Rate:')
        self.range_rate_label.grid(row=7, column=0, padx=5, pady=5, sticky='e')

        self.range_rate_value_label = ttk.Label(self, textvariable=self.range_rate)
        self.range_rate_value_label.grid(row=7, column=1, padx=5, pady=5, sticky='w')

    #===================================================================

    def update_rat_data(self, rat):
        self.zone_value.set(rat.zone)
        self.az_value.set(rat.az_value)
        self.el_value.set(rat.el_value)
        self.range_value.set(rat.range_value)
        self.az_rate.set(rat.az_rate)
        self.el_rate.set(rat.el_rate)
        self.range_rate.set(rat.range_rate)

    #===================================================================

    def start_simulation(self):
        if not self.is_simulating:
            self.is_simulating = True
            self.sim_button.config(text='Stop Simulation', command=self.stop_simulation)

            # Start simulation logic here (e.g., start a thread to update RAT data)
            self.controller.start_rat_sim(self.rat_id)

    #===================================================================

    def stop_simulation(self):
        if self.is_simulating:
            self.is_simulating = False
            self.sim_button.config(text='Start Simulation', command=self.start_simulation)

            # Stop simulation logic here (e.g., stop the thread updating RAT data)
            self.controller.stop_rat_sim(self.rat_id)