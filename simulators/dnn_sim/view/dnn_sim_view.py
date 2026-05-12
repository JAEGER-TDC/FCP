import tkinter as tk
from tkinter import ttk
from view.frames.dnn_sim_simulation_frame import DNNSimSimulationFrame
from view.frames.dnn_sim_mode_frame import DNNSimModeFrame
from view.frames.dnn_sim_data_frame import DataFrame

class DNNSimView(ttk.Frame):
    def __init__(self):
        super().__init__()

        self.controller = None

    #===================================================================

    def init_gui(self):
        self.mode_frame = DNNSimModeFrame(self, self.controller)
        self.mode_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        self.control_frame = DNNSimSimulationFrame(self, self.controller)
        self.control_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        self.sent_data_frame = DataFrame(self, "Sent Data")
        self.sent_data_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        self.recv_data_frame = DataFrame(self, "Received Data")
        self.recv_data_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

    #===================================================================

    def set_controller(self, controller):
        self.controller = controller

