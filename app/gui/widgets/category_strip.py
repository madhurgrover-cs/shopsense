"""The white bar of categories under the header, like Flipkart's top category row:
one icon + name per category. Clicking one filters the shop.

It replaces a drop-down, and keeps a drop-down's small interface: get() returns the
selected name, set(name) selects one without calling back.
"""

from collections.abc import Callable

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, ICONS, PAD_M, PAD_S, PAD_XS


class CategoryStrip(ctk.CTkFrame):
    def __init__(self, parent, all_label: str, on_change: Callable[[str], None]) -> None:
        super().__init__(parent, fg_color=COLORS["surface"], corner_radius=0)
        self._all = all_label
        self._on_change = on_change
        self._selected = all_label
        self._items: dict[str, tuple] = {}  # name -> (icon, text, underline)
        self._row = ctk.CTkFrame(self, fg_color="transparent")
        self._row.pack(anchor="center", pady=(PAD_S, PAD_XS))
        self.set_categories([])
        # 1 px line under the strip, like Flipkart's.
        ctk.CTkFrame(self, height=1, fg_color=COLORS["border"], corner_radius=0).pack(
            fill="x", side="bottom")

    def set_categories(self, names: list[str]) -> None:
        for child in self._row.winfo_children():
            child.destroy()
        self._items.clear()
        self._add(self._all, ICONS["all"])
        for name in names:
            self._add(name, theme.category_style(name)[0])
        if self._selected not in self._items:
            self._selected = self._all
        self._highlight()

    def get(self) -> str:
        return self._selected

    def set(self, name: str) -> None:
        """Select `name` (no callback), like CTkOptionMenu.set()."""
        self._selected = name
        self._highlight()

    def _add(self, name: str, glyph: str) -> None:
        item = ctk.CTkFrame(self._row, fg_color="transparent", corner_radius=0)
        item.pack(side="left", padx=PAD_M + 6)
        icon = ctk.CTkLabel(item, text=glyph, font=theme.icon_font(22), height=30,
                            text_color=COLORS["text"])
        icon.pack()
        # Long names ("Laptops & Computer Accessories") are shortened to the first part.
        short = name.split(" & ")[0] if len(name) > 16 else name
        text = ctk.CTkLabel(item, text=short, font=theme.font(12, "bold"), height=18,
                            text_color=COLORS["text"])
        text.pack()
        # A 2 px underline marks the selected category.
        # (width=1: a CTkFrame asks for 200 px by default, which would stretch the item.)
        line = ctk.CTkFrame(item, height=2, width=1, corner_radius=0, fg_color="transparent")
        line.pack(fill="x", pady=(2, 0))
        for widget in (item, icon, text):
            widget.bind("<Button-1>", lambda _e, n=name: self._click(n))
            widget.configure(cursor="hand2")
        self._items[name] = (icon, text, line)

    def _click(self, name: str) -> None:
        self.set(name)
        self._on_change(name)

    def _highlight(self) -> None:
        for name, (icon, text, line) in self._items.items():
            active = name == self._selected
            color = COLORS["accent"] if active else COLORS["text"]
            icon.configure(text_color=color)
            text.configure(text_color=color)
            line.configure(fg_color=COLORS["accent"] if active else "transparent")
