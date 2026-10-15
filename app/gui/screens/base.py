"""Base class for every screen."""

from typing import TYPE_CHECKING

import customtkinter as ctk

from app.gui.theme import COLORS

if TYPE_CHECKING:
    from app.gui.app import ShopSenseApp


class Screen(ctk.CTkFrame):
    """A page in the main content area. Subclasses set `title` and build their widgets
    in __init__; on_show() runs every time the user navigates to the screen (the place
    to (re)load data in the background).

    Screens talk to the rest of the app only through self.app: self.app.tasks to run
    service calls, self.app.navigate() to change screen, self.app.user for the
    logged-in user. They import services, never the database or AI modules.
    """

    title = ""

    def __init__(self, parent, app: "ShopSenseApp") -> None:
        super().__init__(parent, fg_color=COLORS["bg"], corner_radius=0)
        self.app = app

    def on_show(self, **kwargs) -> None:
        """Called after the screen becomes visible. kwargs come from app.navigate()."""
