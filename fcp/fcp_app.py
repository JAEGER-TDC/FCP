import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import tkinter as tk

from model.fcp_model import FCPModel
from view.fcp_view import FCPView
from controller.fcp_controller import FCPController
import view.theme as theme
from view.cv_launch_dialog import CVLaunchDialog

class FCPApp(tk.Tk):
    def __init__(self):
        super().__init__()

        theme.apply(self)
        self.title('JAEGER Forward Command Post')
        self.geometry('1280x720+50+50')
        icon = tk.PhotoImage(file=os.path.join(os.path.dirname(__file__), 'assets', 'jaeger_logo.png'))
        self.iconphoto(True, icon)

        self._model = FCPModel()
        self._model.analytics_db.start_mission()

        # Log the initial enabled state of all three sensors at mission start
        db = self._model.analytics_db
        for sensor in ('lidar', 'rf', 'acoustic'):
            db.log_sensor_event(sensor, 'enabled')

        self.view = FCPView()
        self.view.pack(fill='both', expand=True)

        self.controller = FCPController(self._model, self.view)
        self.view.set_controller(self.controller)
        _config_path = os.path.join(os.path.dirname(__file__), 'cfg', 'config.ini')
        self.view.init_gui(config_path=_config_path)
        self.view.video_frame.set_load_callback(self.controller.load_video)
        self.view.video_frame.set_alert_callback(self.view.alert_frame.add_alert)
        self.after(100, lambda: CVLaunchDialog(self, self.controller))

        # CV keyboard shortcuts (ignore when focus is in a text-entry widget)
        self.bind('<space>', self._cv_key)
        self.bind('r',       self._cv_key)
        self.bind('s',       self._cv_key)
        self.bind('v',       self._cv_key)
        self.bind('q',       self._cv_key)

        # Do an initial analytics refresh so tables populate immediately
        self.view.analytics_frame.refresh()

        # Close the mission cleanly on window close
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    #===================================================================

    def _cv_key(self, event):
        # Don't fire shortcuts while typing in a text-entry widget
        if isinstance(event.widget, (tk.Text, tk.Entry)):
            return
        k = event.keysym.lower()
        if k == 'space':
            self.controller.cv_pause_toggle()
        elif k == 'r':
            self.controller.cv_reset_tracking()
        elif k == 's':
            self.controller.cv_screenshot()
        elif k == 'v':
            self.controller.cv_restart_video()
        elif k == 'q':
            self._on_close()

    def _on_close(self):
        self.view.save_layout()
        self._model.analytics_db.end_mission()
        self._model.analytics_db.close()
        self.destroy()

if __name__ == '__main__':
    app = FCPApp()
    app.mainloop()
