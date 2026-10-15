"""Admin landing screen. A placeholder for now: the admin screens come in part 2."""

import customtkinter as ctk

from app.gui.screens.base import Screen
from app.gui.theme import COLORS, PAD_L, PAD_S, PAD_XL
from app.gui.widgets.common import card, label, muted


class AdminHomeScreen(Screen):
    title = "Admin"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        box = card(self)
        box.pack(fill="x", padx=PAD_XL, pady=PAD_S)
        self._greeting = label(box, "", size=20, weight="bold")
        self._greeting.pack(fill="x", padx=PAD_L, pady=(PAD_L, PAD_S))
        muted(box, "The admin dashboard, product, stock, order, coupon and review "
                   "management screens are coming in the next step.",
              wraplength=760).pack(fill="x", padx=PAD_L, pady=(0, PAD_L))
        ctk.CTkFrame(box, height=4, width=64, fg_color=COLORS["accent"],
                     corner_radius=2).pack(anchor="w", padx=PAD_L, pady=(0, PAD_L))

    def on_show(self, **kwargs) -> None:
        name = self.app.user.name if self.app.user else ""
        self._greeting.configure(text=f"Welcome, {name}")
