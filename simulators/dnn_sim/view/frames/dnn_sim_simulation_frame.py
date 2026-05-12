import tkinter as tk
from tkinter import ttk
from view.frames.dnn_sim_health_frame import DNNSimHealthFrame
from view.frames.dnn_sim_rat_frame import DNNSimRATFrame

MAX_NUM_RATS = 3

class DNNSimSimulationFrame(ttk.LabelFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, text="Simulation Control")

        self.controller = controller
        self.rat_frames = []

        self.create_widgets()

        for col in range(MAX_NUM_RATS + 1):   # +1 for the health frame
            self.columnconfigure(col, weight=1, uniform="subframe")

    #===================================================================

    def create_widgets(self):
        self.health_frame = DNNSimHealthFrame(self, self.controller)
        self.health_frame.grid(row=0, column=0, padx=10, pady=10, sticky='nsew')

        for i in range(MAX_NUM_RATS):
            rat_frame = DNNSimRATFrame(self, i+1, self.controller)
            rat_frame.grid(row=0, column=i+1, padx=10, pady=10, sticky='nsew')
            self.rat_frames.append(rat_frame)
