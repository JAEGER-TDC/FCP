import tkinter.ttk as ttk

# ---------------------------------------------------------------------------
# Font configuration — change these values to update fonts application-wide
# ---------------------------------------------------------------------------
FONT_FAMILY  = 'Helvetica'
FONT_NORMAL  = (FONT_FAMILY, 14)
FONT_BOLD    = (FONT_FAMILY, 14, 'bold')
FONT_SMALL   = (FONT_FAMILY, 12)
FONT_HEADING = (FONT_FAMILY, 16, 'bold')


def apply(root):
    """Configure ttk styles with the application font.

    Call once after the root Tk() window is created.
    """
    style = ttk.Style(root)
    style.configure('TLabel',            font=FONT_NORMAL)
    style.configure('TButton',           font=FONT_NORMAL)
    style.configure('TEntry',            font=FONT_NORMAL)
    style.configure('TLabelframe.Label', font=FONT_BOLD)
    style.configure('Treeview',          font=FONT_NORMAL)
    style.configure('Treeview.Heading',  font=FONT_BOLD)
    style.configure('TCheckbutton',      font=FONT_NORMAL)
    style.configure('TRadiobutton',      font=FONT_NORMAL)
    style.configure('TCombobox',         font=FONT_NORMAL)
