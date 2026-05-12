"""
CVTuningPanel — floating Toplevel for live CV engine parameter tuning.
Opened by the gear button on the video frame.
"""

import tkinter as tk
from tkinter import ttk

_BG    = "#1a1a2e"
_FG    = "#e0e0e0"
_SECH  = "#7ec8e3"
_TROW  = "#0f3460"
_ENTRY = "#16213e"

# Human-readable label for each config attribute
# bool attrs → (display_name,)  →  "Enabled X" / "Disabled X"
# others     → (display_name, fmt)
_LABELS: dict = {
    'CONF_ACQUIRE':           ('Conf Acquire',      '{:.3f}'),
    'CONF_HOLD':              ('Conf Hold',          '{:.3f}'),
    'CONF_HINT':              ('Conf Hint',          '{:.3f}'),
    'KALMAN_ENABLED':         ('Kalman Filter',),
    'max_lost_frames':        ('Max Lost Frames',    '{}'),
    'ENGAGE_RADIUS_PX':       ('Engage Radius',      '{} px'),
    'DARK_SEARCH_ENABLED':    ('Dark Search',),
    'DARK_COLOR_CHECK':       ('Sky Color Ring',),
    'DARK_PIXEL_RATIO':       ('Dark Pixel Ratio',   '{:.2f}'),
    'DARK_MIN_AREA':          ('Min Blob Area',      '{} px²'),
    'DARK_MAX_AREA':          ('Max Blob Area',      '{} px²'),
    'DARK_SEARCH_RADIUS':     ('Search Radius',      '{} px'),
    'DARK_GRACE_FRAMES':      ('Grace Frames',       '{}'),
    'DARK_LOCK_CONF_TIMEOUT': ('Conf Timeout',       '{} frames'),
    'oef_min_cutoff':         ('OEF Min Cutoff',     '{:.4f}'),
    'oef_beta':               ('OEF Beta',           '{:.5f}'),
    'SHOW_HUD_PANEL':         ('HUD Panel',),
    'SHOW_FPS':               ('FPS Counter',),
    'SHOW_CROSSHAIR':         ('Crosshair',),
    'SHOW_LOCK_RING':         ('Lock Ring',),
    'SHOW_LASER_CENTER':      ('Laser Center',),
    'SHOW_OFFSET_LINE':       ('Offset Line',),
    'SHOW_GIMBAL_ERROR':      ('Gimbal Error',),
    'SHOW_TRAIL':             ('Position Trail',),
    'SHOW_ZOOM_INSET':        ('Zoom Inset',),
    'SHOW_VELOCITY_ARROW':    ('Velocity Arrow',),
    'SHOW_DARK_BLOBS':        ('Dark Blobs',),
}


def _format_alert(attr: str, value) -> str:
    """Return a human-readable tuning change string for the alert frame."""
    entry = _LABELS.get(attr)
    if entry is None:
        return f"CV tuning: {attr} = {value}"
    name = entry[0]
    if len(entry) == 1:            # boolean
        return f"CV: {'Enabled' if value else 'Disabled'} {name}"
    return f"CV: {name} → {entry[1].format(value)}"


def _section(parent, title: str) -> tk.LabelFrame:
    return tk.LabelFrame(
        parent, text=title, bg=_BG, fg=_SECH,
        font=("Helvetica", 9, "bold"),
        relief="groove", bd=1, padx=6, pady=4,
    )


def _label_row(parent, text: str, widget, row: int):
    tk.Label(parent, text=text, bg=_BG, fg=_FG,
             font=("Helvetica", 9), anchor="w").grid(
        row=row, column=0, sticky="w", padx=(0, 8), pady=2)
    widget.grid(row=row, column=1, sticky="w", pady=2)


class CVTuningPanel(tk.Toplevel):
    """Live-tuning panel for CVEngine config fields."""

    def __init__(self, parent, engine, alert_cb=None):
        super().__init__(parent)
        self.title("CV Engine Tuning")
        self.configure(bg=_BG)
        self.resizable(False, True)
        self._engine   = engine
        self._alert_cb = alert_cb

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Dark.TNotebook",        background=_BG, borderwidth=0)
        style.configure("Dark.TNotebook.Tab",    background=_TROW, foreground=_FG,
                         padding=[10, 4], font=("Helvetica", 9))
        style.map("Dark.TNotebook.Tab",          background=[("selected", _BG)],
                                                  foreground=[("selected", _SECH)])

        nb = ttk.Notebook(self, style="Dark.TNotebook")
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self._build_tracking_tab(nb)
        self._build_dark_search_tab(nb)
        self._build_display_tab(nb)

        self.lift()

    # ── Engine swap (called when user loads a new video) ──────────────────

    def set_engine(self, engine) -> None:
        self._engine = engine

    # ── Helpers ───────────────────────────────────────────────────────────

    def _cfg(self):
        return getattr(self._engine, '_cfg', None)

    def _update(self, attr: str, value) -> None:
        if self._engine is None:
            return
        # CVEngine has update_config(); CVEngineSimulator takes direct setattr
        if hasattr(self._engine, 'update_config'):
            self._engine.update_config(attr, value)
        else:
            cfg = self._cfg()
            if cfg is not None:
                setattr(cfg, attr, value)
        if self._alert_cb is not None:
            self._alert_cb(_format_alert(attr, value))

    def _make_scale(self, parent, attr: str, from_: float, to: float,
                    resolution: float = 0.01, fmt: str = "{:.3f}") -> tk.Frame:
        val0 = getattr(self._cfg(), attr)
        var  = tk.DoubleVar(value=val0)

        frame = tk.Frame(parent, bg=_BG)
        lbl   = tk.Label(frame, text=fmt.format(val0), bg=_BG, fg=_SECH,
                         font=("Courier", 9), width=8, anchor="w")

        def on_change(v):
            val = round(float(v), 6)
            lbl.config(text=fmt.format(val))
            self._update(attr, val)

        sc = tk.Scale(
            frame, variable=var, from_=from_, to=to,
            resolution=resolution, orient="horizontal",
            command=on_change,
            bg=_BG, fg=_FG, troughcolor=_TROW,
            highlightthickness=0, sliderrelief="flat",
            length=170, showvalue=False,
        )
        sc.pack(side="left")
        lbl.pack(side="left", padx=(6, 0))
        return frame

    def _make_spinbox(self, parent, attr: str, from_: float, to: float,
                      inc: float = 1, is_float: bool = False) -> tk.Spinbox:
        var = tk.StringVar(value=str(getattr(self._cfg(), attr)))

        def on_change(*_):
            try:
                val = float(var.get()) if is_float else int(var.get())
                val = max(from_, min(to, val))
                self._update(attr, val)
            except ValueError:
                pass

        sp = tk.Spinbox(
            parent, textvariable=var, from_=from_, to=to,
            increment=inc, width=10,
            command=on_change,
            bg=_ENTRY, fg=_FG, insertbackground=_FG,
            buttonbackground=_TROW, relief="flat",
            font=("Courier", 9),
        )
        sp.bind("<FocusOut>", on_change)
        sp.bind("<Return>",   on_change)
        return sp

    def _make_check(self, parent, attr: str, label: str) -> tk.Checkbutton:
        var = tk.BooleanVar(value=getattr(self._cfg(), attr))

        def on_change():
            self._update(attr, var.get())

        return tk.Checkbutton(
            parent, text=label, variable=var, command=on_change,
            bg=_BG, fg=_FG, selectcolor=_ENTRY,
            activebackground=_BG, activeforeground=_FG,
            font=("Helvetica", 9),
        )

    # ── Tabs ──────────────────────────────────────────────────────────────

    def _build_tracking_tab(self, nb: ttk.Notebook):
        outer = tk.Frame(nb, bg=_BG, padx=8, pady=6)
        nb.add(outer, text="Tracking")

        # Confidence
        sec = _section(outer, "Confidence Thresholds")
        sec.pack(fill="x", pady=(0, 8))
        sec.columnconfigure(1, weight=1)
        for row, (lbl, attr, lo, hi, res) in enumerate([
            ("Acquire",  "CONF_ACQUIRE", 0.05, 0.50, 0.01),
            ("Hold",     "CONF_HOLD",    0.02, 0.20, 0.005),
            ("Hint",     "CONF_HINT",    0.01, 0.10, 0.005),
        ]):
            _label_row(sec, lbl, self._make_scale(sec, attr, lo, hi, res), row)

        tk.Label(sec, text="Acquire: lock-on threshold  |  Hold: stay-locked threshold",
                 bg=_BG, fg="#555", font=("Helvetica", 8, "italic")).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # Kalman
        sec2 = _section(outer, "Kalman Filter (PREDICTING mode)")
        sec2.pack(fill="x", pady=(0, 8))
        sec2.columnconfigure(1, weight=1)
        self._make_check(sec2, "KALMAN_ENABLED", "Enabled").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=2)
        _label_row(sec2, "Max lost frames", self._make_spinbox(sec2, "max_lost_frames", 5, 300, 5), 1)

        # Engagement
        sec3 = _section(outer, "Engagement")
        sec3.pack(fill="x")
        sec3.columnconfigure(1, weight=1)
        _label_row(sec3, "Lock radius (px)",
                   self._make_spinbox(sec3, "ENGAGE_RADIUS_PX", 10, 120, 5), 0)
        tk.Label(sec3, text="Gimbal error must be < this for on_target=True",
                 bg=_BG, fg="#555", font=("Helvetica", 8, "italic")).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 2))

    def _build_dark_search_tab(self, nb: ttk.Notebook):
        outer = tk.Frame(nb, bg=_BG, padx=8, pady=6)
        nb.add(outer, text="Dark Search")

        sec = _section(outer, "Dark-Pixel Search")
        sec.pack(fill="x")
        sec.columnconfigure(1, weight=1)

        def hint(row, txt):
            tk.Label(sec, text=txt, bg=_BG, fg="#555",
                     font=("Helvetica", 8, "italic")).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))

        r = 0
        self._make_check(sec, "DARK_SEARCH_ENABLED", "Enabled").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(2, 0)); r += 1
        self._make_check(sec, "DARK_COLOR_CHECK",
                         "Blue-sky color ring filter (disable if overcast)").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(0, 2)); r += 1

        _label_row(sec, "Pixel ratio",
                   self._make_scale(sec, "DARK_PIXEL_RATIO", 0.30, 0.80, 0.01), r); r += 1
        hint(r, "Blob < sky × ratio  |  lower = only very dark blobs"); r += 1

        _label_row(sec, "Min area (px²)",
                   self._make_spinbox(sec, "DARK_MIN_AREA", 10, 10000, 50), r); r += 1
        hint(r, "~30ft drone ≈ 500–3000px²   ~100ft ≈ 30–150px²"); r += 1

        _label_row(sec, "Max area (px²)",
                   self._make_spinbox(sec, "DARK_MAX_AREA", 1000, 100000, 500), r); r += 1

        _label_row(sec, "Search radius",
                   self._make_spinbox(sec, "DARK_SEARCH_RADIUS", 50, 600, 10), r); r += 1
        hint(r, "Raise for fast-moving drones"); r += 1

        _label_row(sec, "Grace frames",
                   self._make_spinbox(sec, "DARK_GRACE_FRAMES", 2, 30, 1), r); r += 1
        hint(r, "Hold DARK LOCK through brief misses"); r += 1

        _label_row(sec, "Conf timeout",
                   self._make_spinbox(sec, "DARK_LOCK_CONF_TIMEOUT", 5, 60, 1), r); r += 1
        hint(r, "Release false-lock if CV gives no signal"); r += 1

    def _build_display_tab(self, nb: ttk.Notebook):
        outer = tk.Frame(nb, bg=_BG, padx=8, pady=6)
        nb.add(outer, text="Display")

        # Smoothing
        sec = _section(outer, "Position Smoothing (One-Euro Filter)")
        sec.pack(fill="x", pady=(0, 8))
        sec.columnconfigure(1, weight=1)
        _label_row(sec, "Min cutoff",
                   self._make_scale(sec, "oef_min_cutoff", 0.01, 0.20, 0.005), 0)
        _label_row(sec, "Beta",
                   self._make_scale(sec, "oef_beta", 0.0001, 0.01, 0.0001, "{:.4f}"), 1)
        tk.Label(sec, text="Smoothing resets the filter — brief jump is normal",
                 bg=_BG, fg="#555", font=("Helvetica", 8, "italic")).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(0, 2))

        # HUD overlays
        sec2 = _section(outer, "HUD Overlays")
        sec2.pack(fill="x")
        toggles = [
            ("SHOW_HUD_PANEL",      "HUD info panel"),
            ("SHOW_FPS",            "FPS counter"),
            ("SHOW_CROSSHAIR",      "Crosshair on drone"),
            ("SHOW_LOCK_RING",      "Lock ring"),
            ("SHOW_LASER_CENTER",   "Laser center marker"),
            ("SHOW_OFFSET_LINE",    "Laser→drone line"),
            ("SHOW_GIMBAL_ERROR",   "Gimbal error text"),
            ("SHOW_TRAIL",          "Position trail"),
            ("SHOW_ZOOM_INSET",     "Zoom inset"),
            ("SHOW_VELOCITY_ARROW", "Velocity arrow"),
            ("SHOW_DARK_BLOBS",     "Dark blob candidates"),
        ]
        for i, (attr, lbl) in enumerate(toggles):
            self._make_check(sec2, attr, lbl).grid(
                row=i // 2, column=i % 2, sticky="w", padx=6, pady=2)
