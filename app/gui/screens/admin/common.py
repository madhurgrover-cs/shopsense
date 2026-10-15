"""Small building blocks shared by the admin screens (toolbars, buttons, drop-downs)."""

from collections.abc import Callable

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, CORNER_RADIUS, PAD_M, PAD_S, PAD_XL


def toolbar(screen) -> ctk.CTkFrame:
    """The row of controls at the top of a screen."""
    bar = ctk.CTkFrame(screen, fg_color="transparent")
    bar.pack(fill="x", padx=PAD_XL, pady=(PAD_S, PAD_M))
    return bar


def button(parent, text: str, command: Callable[[], None], kind: str = "secondary",
           width: int = 120) -> ctk.CTkButton:
    """kind: "primary" (main action), "secondary", or "danger" (delete / cancel)."""
    if kind == "primary":
        style = theme.primary_button_style()
    else:
        style = theme.secondary_button_style()
        if kind == "danger":
            style.update(text_color=COLORS["danger"], border_color=COLORS["danger"])
    return ctk.CTkButton(parent, text=text, command=command, width=width,
                         text_color_disabled=COLORS["text_muted"],
                         **{k: v for k, v in style.items() if k != "text_color_disabled"})


def dropdown(parent, values: list[str], command: Callable[[str], None],
             width: int = 180) -> ctk.CTkOptionMenu:
    return ctk.CTkOptionMenu(
        parent, values=values, command=command, width=width, height=38,
        corner_radius=CORNER_RADIUS, font=theme.body_font(), fg_color=COLORS["surface"],
        button_color=COLORS["surface_hover"], button_hover_color=COLORS["border"],
        text_color=COLORS["text"], dropdown_fg_color=COLORS["surface"],
        dropdown_text_color=COLORS["text"], dropdown_font=theme.body_font())


def search_box(parent, placeholder: str, on_change: Callable[[], None],
               width: int = 280) -> ctk.CTkEntry:
    """A filter box that calls on_change() on every key press (filtering happens in
    memory, on rows already loaded, so it's instant)."""
    entry = ctk.CTkEntry(parent, placeholder_text=placeholder, width=width, height=38,
                         corner_radius=CORNER_RADIUS, font=theme.body_font(),
                         fg_color=COLORS["surface"], border_color=COLORS["border"],
                         text_color=COLORS["text"])
    entry.bind("<KeyRelease>", lambda _e: on_change())
    return entry


def set_enabled(widget, enabled: bool) -> None:
    widget.configure(state="normal" if enabled else "disabled")
