"""The admin's slim white navigation on the left, one row per screen (customers have no
sidebar: they navigate with the header links and the category strip)."""

from collections.abc import Callable

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, PAD_M, PAD_S, SIDEBAR_WIDTH


class Sidebar(ctk.CTkFrame):
    def __init__(self, parent, on_navigate: Callable[[str], None]) -> None:
        super().__init__(parent, width=SIDEBAR_WIDTH, corner_radius=0,
                         fg_color=COLORS["sidebar"])
        self.grid_propagate(False)  # keep the fixed width
        self._on_navigate = on_navigate
        self._rows: dict[str, tuple[ctk.CTkFrame, ctk.CTkButton]] = {}

        ctk.CTkLabel(self, text="MANAGE", font=theme.font(11, "bold"),
                     text_color=COLORS["text_muted"], anchor="w").pack(
            fill="x", padx=PAD_M + 4, pady=(PAD_M, PAD_S))
        self._nav = ctk.CTkFrame(self, fg_color="transparent")
        self._nav.pack(fill="x")
        # 1 px line separating the nav from the grey content area.
        ctk.CTkFrame(self, width=1, height=1, fg_color=COLORS["border"], corner_radius=0).place(
            relx=1.0, rely=0, relheight=1.0, anchor="ne")

    def set_items(self, items: list[tuple[str, str]]) -> None:
        """items = [(screen key, label)]. Replaces the current rows."""
        for row, _button in self._rows.values():
            row.destroy()
        self._rows.clear()
        for key, label in items:
            row = ctk.CTkFrame(self._nav, fg_color="transparent", corner_radius=0, height=38)
            row.pack(fill="x")
            row.pack_propagate(False)
            # A 3 px blue bar on the left marks the active screen (shown in set_active).
            bar = ctk.CTkFrame(row, width=3, height=1, fg_color=COLORS["accent"], corner_radius=0)
            bar.pack(side="left", fill="y")
            bar.pack_forget()
            button = ctk.CTkButton(
                row, text=label, anchor="w", height=38, corner_radius=0,
                font=theme.font(13), fg_color="transparent", text_color=COLORS["text"],
                hover_color=COLORS["surface_hover"],
                command=lambda k=key: self._on_navigate(k))
            button.pack(side="left", fill="both", expand=True, padx=(PAD_S, 1))
            row.active_bar = bar
            self._rows[key] = (row, button)

    def set_active(self, key: str) -> None:
        """Highlight the row of the screen being shown."""
        for row_key, (row, button) in self._rows.items():
            active = row_key == key
            row.configure(fg_color=COLORS["selected_nav"] if active else "transparent")
            button.configure(text_color=COLORS["accent"] if active else COLORS["text"],
                             font=theme.font(13, "bold" if active else "normal"),
                             hover_color=COLORS["selected_nav"] if active
                             else COLORS["surface_hover"])
            if active:
                row.active_bar.pack(side="left", fill="y", before=button)
            else:
                row.active_bar.pack_forget()
