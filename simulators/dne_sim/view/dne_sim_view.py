import tkinter as tk
from tkinter import ttk
from view.frames.dne_sim_status_frame import DNESimStatusFrame
from view.frames.dne_sim_targeting_frame import DNESimTargetingFrame
from view.frames.dne_sim_data_frame import DataFrame

class DNESimView(ttk.Frame):
    def __init__(self):
        super().__init__()
        self.controller = None

    #===================================================================

    def init_gui(self):
        # Left column: status controls + targeting data
        left = ttk.Frame(self)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.status_frame = DNESimStatusFrame(left, self.controller)
        self.status_frame.pack(fill=tk.X, pady=(0, 10))

        self.targeting_frame = DNESimTargetingFrame(left)
        self.targeting_frame.pack(fill=tk.X)

        # Right column: received message log
        self.recv_data_frame = DataFrame(self, 'Received Messages')
        self.recv_data_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

    #===================================================================

    def set_controller(self, controller):
        self.controller = controller
