import configparser
import tkinter as tk
from tkinter import ttk
from view.frames import video_frame, map_frame, alert_frame, control_frame
from view.frames.analytics_frame import AnalyticsFrame

_SASH_SECTION = 'layout.sash'

class FCPView(ttk.Frame):
    def __init__(self):
        super().__init__()
        self._config_path: str | None = None

    #===================================================================

    def init_gui(self, config_path: str | None = None):
        self._config_path = config_path

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._v_pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self._v_pane.grid(row=0, column=0, sticky='nsew')

        self._top_pane = ttk.PanedWindow(self._v_pane, orient=tk.HORIZONTAL)
        self._v_pane.add(self._top_pane, weight=2)

        self._bot_pane = ttk.PanedWindow(self._v_pane, orient=tk.HORIZONTAL)
        self._v_pane.add(self._bot_pane, weight=2)

        self.video_frame = video_frame.VideoFrame(self._top_pane)
        self._top_pane.add(self.video_frame, weight=2)
        # CV engine started after CVLaunchDialog — not auto-started here

        self.map_frame = map_frame.MapFrame(self._top_pane)
        self._top_pane.add(self.map_frame, weight=2)

        # Bottom-left: controls (fixed height) stacked above alert log (expands)
        _left_bottom = ttk.Frame(self._bot_pane)
        self._bot_pane.add(_left_bottom, weight=3)
        _left_bottom.columnconfigure(0, weight=1)
        _left_bottom.rowconfigure(0, weight=0)
        _left_bottom.rowconfigure(1, weight=1)

        self.control_frame = control_frame.ControlFrame(_left_bottom, controller=self.controller)
        self.control_frame.grid(row=0, column=0, sticky='nsew')

        self.alert_frame = alert_frame.AlertFrame(_left_bottom)
        self.alert_frame.grid(row=1, column=0, sticky='nsew')

        self.analytics_frame = AnalyticsFrame(self._bot_pane, db=self.controller.model.analytics_db)
        self._bot_pane.add(self.analytics_frame, weight=2)

        if config_path:
            self.after(200, self._restore_layout)

    #===================================================================

    def save_layout(self):
        if not self._config_path:
            return
        v_h   = self._v_pane.winfo_height()
        top_w = self._top_pane.winfo_width()
        bot_w = self._bot_pane.winfo_width()
        if v_h < 10 or top_w < 10 or bot_w < 10:
            return

        v_frac   = self._v_pane.sashpos(0)   / v_h
        top_frac = self._top_pane.sashpos(0) / top_w
        bot_frac = self._bot_pane.sashpos(0) / bot_w

        config = configparser.ConfigParser()
        config.read(self._config_path)
        if not config.has_section(_SASH_SECTION):
            config.add_section(_SASH_SECTION)
        config[_SASH_SECTION]['vertical']        = f'{v_frac:.4f}'
        config[_SASH_SECTION]['top_horizontal']  = f'{top_frac:.4f}'
        config[_SASH_SECTION]['bot_horizontal']  = f'{bot_frac:.4f}'
        with open(self._config_path, 'w') as f:
            config.write(f)

    def _restore_layout(self):
        config = configparser.ConfigParser()
        config.read(self._config_path)
        if not config.has_section(_SASH_SECTION):
            return

        sect = config[_SASH_SECTION]
        v_frac   = sect.getfloat('vertical',       fallback=None)
        top_frac = sect.getfloat('top_horizontal',  fallback=None)
        bot_frac = sect.getfloat('bot_horizontal',  fallback=None)

        # Flush any pending layout passes so winfo_* sizes are current before we read them
        self.update_idletasks()

        if v_frac is not None:
            v_h = self._v_pane.winfo_height()
            if v_h > 10:
                self._v_pane.sashpos(0, int(v_frac * v_h))

        # Flush the v_pane reflow before setting sashes on its children; otherwise
        # Tkinter's deferred reflow resets _bot_pane's sash back to the weight default.
        self.update_idletasks()

        if top_frac is not None:
            top_w = self._top_pane.winfo_width()
            if top_w > 10:
                self._top_pane.sashpos(0, int(top_frac * top_w))

        if bot_frac is not None:
            bot_w = self._bot_pane.winfo_width()
            if bot_w > 10:
                self._bot_pane.sashpos(0, int(bot_frac * bot_w))

    #===================================================================

    def set_controller(self, controller):
        self.controller = controller
