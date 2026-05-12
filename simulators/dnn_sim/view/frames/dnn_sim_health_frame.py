import tkinter as tk
from tkinter import ttk

class DNNSimHealthFrame(ttk.LabelFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, text="Health and Status")

        self.controller = controller

        self.is_simulating = False

        self.battery_percent = tk.DoubleVar(value=0.0)
        self.temperature_c = tk.DoubleVar(value=0.0)
        self.error_code = tk.IntVar(value=0)
        self.status_flag = tk.StringVar(value='')

        self.create_widgets()

        self.columnconfigure(0, weight=1, uniform="subframe")
        self.columnconfigure(1, weight=1, uniform="subframe")

    #===================================================================

    def create_widgets(self):
        self.sim_button = ttk.Button(self, text='Start Simulation', command=self.start_simulation)
        self.sim_button.grid(row=0, column=0, columnspan=2, padx=5, pady=5)

        self.battery_percent_label = ttk.Label(self, text='Battery Percentage:')
        self.battery_percent_label.grid(row=1, column=0, padx=5, pady=5, sticky='e')

        self.battery_percent_value_label = ttk.Label(self, textvariable=self.battery_percent)
        self.battery_percent_value_label.grid(row=1, column=1, padx=5, pady=5, sticky='w')

        self.temperature_c_label = ttk.Label(self, text='Temperature (°C):')
        self.temperature_c_label.grid(row=2, column=0, padx=5, pady=5, sticky='e')

        self.temperature_c_value_label = ttk.Label(self, textvariable=self.temperature_c)
        self.temperature_c_value_label.grid(row=2, column=1, padx=5, pady=5, sticky='w')

        self.error_code_label = ttk.Label(self, text='Error Code:')
        self.error_code_label.grid(row=3, column=0, padx=5, pady=5, sticky='e')

        self.error_code_value_label = ttk.Label(self, textvariable=self.error_code)
        self.error_code_value_label.grid(row=3, column=1, padx=5, pady=5, sticky='w')

        self.status_flag_label = ttk.Label(self, text='Status Flag:')
        self.status_flag_label.grid(row=4, column=0, padx=5, pady=5, sticky='e')

        self.status_flag_value_label = ttk.Label(self, textvariable=self.status_flag)
        self.status_flag_value_label.grid(row=4, column=1, padx=5, pady=5, sticky='w')

    #===================================================================

    def set_controller(self, controller):
        self.controller = controller
        print("Controller set in DNNSimHealthFrame")

    #===================================================================

    def update_health(self, battery, temperature_c, error_code, status_flag):
        """Copy the model's health fields into the displayed Tkinter variables."""
        self.battery_percent.set(battery)
        self.temperature_c.set(temperature_c)
        self.error_code.set(error_code)
        self.status_flag.set(status_flag)

    #===================================================================

    def start_simulation(self):
        if not self.is_simulating:
            self.is_simulating = True
            self.sim_button.config(text='Stop Simulation',
                                   command=self.stop_simulation)
            if self.controller:
                self.controller.start_health_sim()

    #===================================================================

    def stop_simulation(self):
        if self.is_simulating:
            self.is_simulating = False
            self.sim_button.config(text='Start Simulation',
                                   command=self.start_simulation)
            if self.controller:
                self.controller.stop_health_sim()