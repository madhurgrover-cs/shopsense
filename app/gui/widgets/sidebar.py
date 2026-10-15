"""Left navigation bar: app name at the top, one button per screen."""

from collections.abc import Callable

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S, PAD_XS, SIDEBAR_WIDTH


class Sidebar(ctk.CTkFrame):
    def __init__(self, parent, on_navigate: Callable[[str], None]) -> None:
        super().__init__(parent, width=SIDEBAR_WIDTH, corner_radius=0,
                         fg_color=COLORS["sidebar"])
        self.grid_propagate(False)  # keep the fixed width
        self._on_navigate = on_navigate
        self._buttons: dict[str, ctk.CTkButton] = {}

        # Logo: accent dot + name.
        logo = ctk.CTkFrame(self, fg_color="transparent")
        logo.pack(fill="x", padx=PAD_L, pady=(PAD_L, PAD_L + PAD_S))
        ctk.CTkFrame(logo, width=12, height=12, corner_radius=6,
                     fg_color=COLORS["accent"]).pack(side="left", padx=(0, PAD_S))
        ctk.CTkLabel(logo, text=theme.APP_NAME, font=theme.font(20, "bold"),
                     text_color=COLORS["text"]).pack(side="left")

        self._nav = ctk.CTkFrame(self, fg_color="transparent")
        self._nav.pack(fill="x", padx=PAD_M)

        # Bottom area (e.g. the logged-in user), filled by the app.
        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.pack(side="bottom", fill="x", padx=PAD_M, pady=PAD_M)

    def set_items(self, items: list[tuple[str, str]]) -> None:
        """items = [(screen key, label)]. Replaces the current buttons
        (the menu differs for guests, customers and admins)."""
        for button in self._buttons.values():
            button.destroy()
        self._buttons.clear()
        for key, label in items:
            button = ctk.CTkButton(
                self._nav, text=label, anchor="w", height=40, corner_radius=8,
                font=theme.font(14), fg_color="transparent", text_color=COLORS["text_muted"],
                hover_color=COLORS["surface_hover"],
                command=lambda k=key: self._on_navigate(k),
            )
            button.pack(fill="x", pady=PAD_XS)
            self._buttons[key] = button

    def set_active(self, key: str) -> None:
        """Highlight the button of the screen being shown."""
        for button_key, button in self._buttons.items():
            active = button_key == key
            button.configure(
                fg_color=COLORS["surface"] if active else "transparent",
                text_color=COLORS["text"] if active else COLORS["text_muted"],
                font=theme.font(14, "bold" if active else "normal"),
            )
