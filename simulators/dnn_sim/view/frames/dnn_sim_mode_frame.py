import tkinter as tk
from tkinter import ttk

class DNNSimModeFrame(ttk.LabelFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, text='Simulation Mode')

        self.controller = controller

        self.lidar_enabled = True
        self.rf_enabled = True
        self.acoustic_enabled = True

        self.create_widgets()

        # Configure grid weights to allow expansion
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, weight=1)

    #===================================================================

    def create_widgets(self):
        self.lidar_status = ttk.Label(self, text='LiDAR Enabled')
        self.lidar_status.configure(background='lightgreen' if self.lidar_enabled else 'red', anchor=tk.CENTER)
        self.lidar_status.grid(row=0, column=0, padx=5, pady=5, sticky='nsew')

        self.rf_status = ttk.Label(self, text='RF Enabled')
        self.rf_status.configure(background='lightgreen' if self.rf_enabled else 'red', anchor=tk.CENTER)
        self.rf_status.grid(row=0, column=1, padx=5, pady=5, sticky='nsew')

        self.acoustic_status = ttk.Label(self, text='Acoustic Enabled')
        self.acoustic_status.configure(background='lightgreen' if self.acoustic_enabled else 'red', anchor=tk.CENTER)
        self.acoustic_status.grid(row=0, column=2, padx=5, pady=5, sticky='nsew')

    #===================================================================

    def set_lidar_enabled(self, enabled):
        self.lidar_enabled = enabled
        self.lidar_status.configure(background='lightgreen' if self.lidar_enabled else 'red')
        self.lidar_status.configure(text='LiDAR Enabled' if self.lidar_enabled else 'LiDAR Disabled')

    #===================================================================

    def set_rf_enabled(self, enabled):
        self.rf_enabled = enabled
        self.rf_status.configure(background='lightgreen' if self.rf_enabled else 'red')
        self.rf_status.configure(text='RF Enabled' if self.rf_enabled else 'RF Disabled')

    #===================================================================

    def set_acoustic_enabled(self, enabled):
        self.acoustic_enabled = enabled
        self.acoustic_status.configure(background='lightgreen' if self.acoustic_enabled else 'red')
        self.acoustic_status.configure(text='Acoustic Enabled' if self.acoustic_enabled else 'Acoustic Disabled')