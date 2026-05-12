"""
CVLaunchDialog — startup mode selection shown once when JAEGER launches.
Presents 3 mutually exclusive CV operating modes.
"""

import tkinter as tk
from tkinter import filedialog

_BG   = "#0d1117"
_CARD = "#161b22"
_FG   = "#e0e0e0"
_DIM  = "#8b949e"
_ACC  = "#7ec8e3"


def _bind_all(widget, event, callback):
    """Bind an event to a widget and all its descendants."""
    widget.bind(event, callback)
    for child in widget.winfo_children():
        _bind_all(child, event, callback)


class _ModeCard(tk.Frame):
    """Clickable card for one CV mode option."""

    def __init__(self, parent, icon: str, title: str, subtitle: str,
                 accent: str, command):
        super().__init__(parent, bg=_CARD, cursor="hand2",
                         highlightthickness=1, highlightbackground="#30363d")
        self._accent = accent
        self._command = command

        icon_lbl = tk.Label(self, text=icon, bg=_CARD, fg=accent,
                            font=("Helvetica", 22))
        icon_lbl.grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=14)

        tk.Label(self, text=title, bg=_CARD, fg=accent,
                 font=("Helvetica", 11, "bold"), anchor="w").grid(
            row=0, column=1, sticky="sw", pady=(12, 0))

        tk.Label(self, text=subtitle, bg=_CARD, fg=_DIM,
                 font=("Helvetica", 9), anchor="w").grid(
            row=1, column=1, sticky="nw", pady=(0, 12))

        self.columnconfigure(1, weight=1)

        _bind_all(self, "<Enter>",    lambda e: self._hover(True))
        _bind_all(self, "<Leave>",    lambda e: self._hover(False))
        _bind_all(self, "<Button-1>", lambda e: command())

    def _hover(self, on: bool):
        colour = self._accent if on else "#30363d"
        self.config(highlightbackground=colour)


class CVLaunchDialog(tk.Toplevel):
    """Modal startup dialog — user must pick a CV mode before the mission begins."""

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.title("JAEGER — Select Operating Mode")
        self.configure(bg=_BG)
        self.resizable(False, False)
        self._controller = controller

        # Modal — cannot close without picking a mode
        self.grab_set()
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        # Centre over parent
        parent.update_idletasks()
        w, h = 480, 340
        px = parent.winfo_rootx() + max(0, (parent.winfo_width()  - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        self.geometry(f"{w}x{h}+{px}+{py}")

        # ── Header ────────────────────────────────────────────────────────
        tk.Label(self, text="JAEGER  TURBODRONE  C2",
                 bg=_BG, fg=_ACC, font=("Helvetica", 13, "bold")).pack(pady=(20, 2))
        tk.Label(self, text="Choose a CV operating mode to begin the mission",
                 bg=_BG, fg=_DIM, font=("Helvetica", 9)).pack(pady=(0, 14))

        # ── Mode cards ────────────────────────────────────────────────────
        cards = tk.Frame(self, bg=_BG)
        cards.pack(fill="x", padx=20)

        _ModeCard(cards,
                  icon="▶",
                  title="Simulator",
                  subtitle="Scripted tracking on test video — runs on any machine, no GPU required",
                  accent="#4CAF50",
                  command=self._pick_simulator,
                  ).pack(fill="x", pady=4)

        _ModeCard(cards,
                  icon="📂",
                  title="Load Video  +  Real CV",
                  subtitle="Browse for a video file and run the TensorRT tracking engine",
                  accent=_ACC,
                  command=self._pick_video,
                  ).pack(fill="x", pady=4)

        _ModeCard(cards,
                  icon="📷",
                  title="USB Camera  +  Real CV",
                  subtitle="Live webcam feed processed by the TensorRT tracking engine",
                  accent="#b39ddb",
                  command=self._pick_camera,
                  ).pack(fill="x", pady=4)

        # ── Status line ───────────────────────────────────────────────────
        self._status_var = tk.StringVar()
        tk.Label(self, textvariable=self._status_var,
                 bg=_BG, fg="#e57373",
                 font=("Helvetica", 9)).pack(pady=(8, 4))

    # ── Handlers ──────────────────────────────────────────────────────────

    def _pick_simulator(self):
        self._controller.start_mode_simulator()
        self.destroy()

    def _pick_video(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Select video file for CV tracking",
            filetypes=[
                ("Video files", "*.mp4 *.avi *.mov *.MP4 *.AVI *.MOV"),
                ("All files",   "*.*"),
            ],
        )
        if not path:
            return  # cancelled — keep dialog open
        self._status_var.set("Starting CV engine…")
        self.update_idletasks()
        self._controller.start_mode_video(path)
        self.destroy()

    def _pick_camera(self):
        self._status_var.set("Opening camera…")
        self.update_idletasks()
        self._controller.start_mode_camera()
        self.destroy()
