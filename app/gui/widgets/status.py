"""The small loading indicator in the header: a moving bar plus a message."""

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, PAD_S


class StatusIndicator(ctk.CTkFrame):
    """Fixed size (theme.STATUS_WIDTH): its contents can never resize it, so the search
    box next to it stays put when the indicator appears or disappears.

    on_dark=True: white text and bar, for use on the blue header."""

    def __init__(self, parent, on_dark: bool = False) -> None:
        super().__init__(parent, fg_color="transparent", width=theme.STATUS_WIDTH, height=32)
        self.pack_propagate(False)  # children don't change this frame's size
        text = COLORS["header_muted"] if on_dark else COLORS["text_muted"]
        bar = COLORS["header_text"] if on_dark else COLORS["accent"]
        track = COLORS["accent_hover"] if on_dark else COLORS["border"]
        self._label = ctk.CTkLabel(self, text="", font=theme.small_font(), text_color=text)
        self._bar = ctk.CTkProgressBar(self, width=90, height=4, mode="indeterminate",
                                       corner_radius=2, progress_color=bar, fg_color=track)
        self._visible = False

    def set_busy(self, message: str | None) -> None:
        """Show `message` with an animated bar, or hide everything when None."""
        if message is None:
            if self._visible:
                self._bar.stop()
                self._bar.pack_forget()
                self._label.pack_forget()
                self._visible = False
            return
        self._label.configure(text=message)
        if not self._visible:
            self._bar.pack(side="right")
            self._label.pack(side="right", padx=(0, PAD_S))
            self._bar.start()
            self._visible = True
