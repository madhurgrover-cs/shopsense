"""Modal popups for errors and information."""

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S


class MessageDialog(ctk.CTkToplevel):
    """A small modal window: icon-coloured title, message, OK button.

    Modal = it grabs input, so the user must close it before clicking anything else.
    """

    def __init__(self, parent, title: str, message: str, kind: str = "error") -> None:
        super().__init__(parent)
        self.title(title)
        self.configure(fg_color=COLORS["surface"])
        self.resizable(False, False)
        self.transient(parent)  # stays on top of the main window, no taskbar entry

        accent = {"error": COLORS["danger"], "warning": COLORS["warning"],
                  "info": COLORS["accent"], "success": COLORS["success"]}[kind]

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(padx=PAD_L, pady=PAD_L, fill="both", expand=True)
        ctk.CTkFrame(frame, height=4, width=48, fg_color=accent, corner_radius=2).pack(
            anchor="w", pady=(0, PAD_S))
        ctk.CTkLabel(frame, text=title, font=theme.heading_font(),
                     text_color=COLORS["text"], anchor="w").pack(fill="x")
        ctk.CTkLabel(frame, text=message, font=theme.body_font(),
                     text_color=COLORS["text_muted"], wraplength=380, justify="left",
                     anchor="w").pack(fill="x", pady=(PAD_S, PAD_M))
        ok = ctk.CTkButton(frame, text="OK", width=96, command=self.destroy,
                           **theme.primary_button_style())
        ok.pack(anchor="e")

        self.bind("<Return>", lambda _e: self.destroy())
        self.bind("<Escape>", lambda _e: self.destroy())
        self._center_on(parent)
        # grab_set must wait until the window is visible, or Tk raises an error.
        self.after(50, self._make_modal, ok)

    def _make_modal(self, focus_widget) -> None:
        if self.winfo_exists():
            self.grab_set()
            focus_widget.focus_set()

    def _center_on(self, parent) -> None:
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")


def show_error(parent, title: str, message: str) -> MessageDialog:
    return MessageDialog(parent, title, message, kind="error")


def show_info(parent, title: str, message: str) -> MessageDialog:
    return MessageDialog(parent, title, message, kind="info")
