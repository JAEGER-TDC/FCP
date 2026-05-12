import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import tkinter as tk

from model.dne_sim_model import DNESimModel
from view.dne_sim_view import DNESimView
from controller.dne_sim_controller import DNESimController
import view.theme as theme

class DNESimApp(tk.Tk):
    def __init__(self):
        super().__init__()

        theme.apply(self)
        self.title('JAEGER DNE Simulator')
        self.geometry('900x500+100+100')
        icon = tk.PhotoImage(file=os.path.join(os.path.dirname(__file__), 'assets', 'jaeger_logo.png'))
        self.iconphoto(True, icon)

        self._model = DNESimModel()

        self.view = DNESimView()
        self.view.pack(fill='both', expand=True)

        self.controller = DNESimController(self._model, self.view)
        self.view.set_controller(self.controller)
        self.view.init_gui()

#===================================================================

if __name__ == '__main__':
    app = DNESimApp()
    app.mainloop()
