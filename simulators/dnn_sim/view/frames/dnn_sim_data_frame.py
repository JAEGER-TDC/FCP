import tkinter as tk
from tkinter import ttk

from tkinter.scrolledtext import ScrolledText

class DataFrame(ttk.LabelFrame):
    def __init__(self, parent, title):
        super().__init__(parent, text=title)

        self.create_widgets()

    def create_widgets(self):
        self._alert_text = ScrolledText(self, wrap=tk.WORD)
        self._alert_text.configure(state='disabled')
        self._alert_text.pack(expand=True, fill='both')

    #===================================================================

    def add_alert(self, alert_message):
        self._alert_text.configure(state='normal')
        self._alert_text.insert(tk.END, alert_message + '\n')
        self._alert_text.configure(state='disabled')
        self._alert_text.see(tk.END)  # Scroll to the end to show the latest alert