import tkinter as tk
import os

from model.dnn_sim_model import DNNSimModel
from view.dnn_sim_view import DNNSimView
from controller.dnn_sim_controller import DNNSimController
import view.theme as theme

class DNNSimApp(tk.Tk):
    def __init__(self):
        super().__init__()

        theme.apply(self)
        self.title('JAEGER DNN Simulator')
        self.geometry('1280x720+50+50')
        icon = tk.PhotoImage(file=os.path.join(os.path.dirname(__file__), 'assets', 'jaeger_logo.png'))
        self.iconphoto(True, icon)

        self._model = DNNSimModel()

        self.view = DNNSimView()
        self.view.pack(fill='both', expand=True)

        self.controller = DNNSimController(self._model, self.view)
        self.view.set_controller(self.controller)
        self.view.init_gui()

#===================================================================

if __name__ == '__main__':
    app = DNNSimApp()
    app.mainloop()