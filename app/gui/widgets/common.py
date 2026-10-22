"""Small reusable widgets: pills, panels, icons, category tiles, clickable areas,
quantity stepper. All flat: thin 1 px borders, nearly square corners, no shadows."""

from collections.abc import Callable

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, CORNER_RADIUS, PAD_S


def pill(parent, text: str, color: str) -> ctk.CTkLabel:
    """A small, nearly square coloured label, e.g. an order status."""
    return ctk.CTkLabel(parent, text=f" {text} ", font=theme.font(11, "bold"),
                        text_color=COLORS["on_color"], fg_color=color,
                        corner_radius=CORNER_RADIUS, height=20)


def rating_pill(parent, avg: float | None, count: int) -> ctk.CTkFrame:
    """Flipkart-style rating: a green pill "4.2 ★" then a grey "(12)".
    Products without reviews get a grey "No ratings yet" instead."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    if not count or avg is None:
        muted(row, "No ratings yet", size=12).pack(side="left")
        return row
    ctk.CTkLabel(row, text=f" {avg:.1f} ★ ", font=theme.font(11, "bold"),
                 text_color=COLORS["on_color"], fg_color=COLORS["success"],
                 corner_radius=CORNER_RADIUS, height=18).pack(side="left")
    muted(row, f"({count})", size=12).pack(side="left", padx=(PAD_S, 0))
    return row


def card(parent, **kwargs) -> ctk.CTkFrame:
    """A flat white panel with a thin grey border."""
    options = {"fg_color": COLORS["surface"], "corner_radius": CORNER_RADIUS,
               "border_width": 1, "border_color": COLORS["border"], **kwargs}
    return ctk.CTkFrame(parent, **options)


def icon(parent, glyph: str, size: int = 16, color: str | None = None,
         **kwargs) -> ctk.CTkLabel:
    """A glyph from the Windows icon font (see theme.ICONS / theme.CATEGORY_STYLE)."""
    return ctk.CTkLabel(parent, text=glyph, font=theme.icon_font(size),
                        text_color=color or COLORS["text"], **kwargs)


def category_tile(parent, category: str, height: int, icon_size: int) -> ctk.CTkFrame:
    """A soft-coloured block with the category's icon: stands in for a product photo."""
    glyph, tint = theme.category_style(category)
    tile = ctk.CTkFrame(parent, fg_color=tint, corner_radius=CORNER_RADIUS, height=height)
    tile.pack_propagate(False)  # keep the fixed height
    icon(tile, glyph, size=icon_size, color=COLORS["text_muted"]).place(
        relx=0.5, rely=0.5, anchor="center")
    return tile


def divider(parent) -> ctk.CTkFrame:
    """A 1 px horizontal line."""
    return ctk.CTkFrame(parent, height=1, width=1, fg_color=COLORS["border"], corner_radius=0)


def label(parent, text: str = "", size: int = 14, weight: str = "normal",
          color: str | None = None, **kwargs) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, font=theme.font(size, weight),
                        text_color=color or COLORS["text"], anchor="w", justify="left",
                        **kwargs)


def muted(parent, text: str = "", size: int = 13, **kwargs) -> ctk.CTkLabel:
    return label(parent, text, size=size, color=COLORS["text_muted"], **kwargs)


def section_title(parent, text: str) -> ctk.CTkLabel:
    return label(parent, text, size=15, weight="bold")


def empty_state(parent, text: str) -> ctk.CTkLabel:
    return muted(parent, text, size=13)


def caps_heading(parent, text: str) -> ctk.CTkLabel:
    """Flipkart's grey upper-case box heading, e.g. "PRICE DETAILS"."""
    return label(parent, text.upper(), size=13, weight="bold", color=COLORS["text_muted"])


def auto_wrap(text_label: ctk.CTkLabel, container, padding: int = 0) -> None:
    """Wrap the label's text to the container's CURRENT width (minus padding), and keep
    doing so when the window is resized. A fixed wraplength breaks on screens with
    display scaling: at 150 % a "230 px" wrap is wider than the card it sits in.

    The Configure event reports real pixels, while CTk multiplies wraplength by the
    scaling factor, so we divide by it first.
    """
    def resize(event) -> None:
        scale = ctk.ScalingTracker.get_widget_scaling(text_label)
        text_label.configure(wraplength=max(60, int(event.width / scale) - padding))
    container.bind("<Configure>", resize, add="+")


def make_clickable(frame: ctk.CTkFrame, command: Callable[[], None]) -> None:
    """Make a whole card clickable: the frame and everything inside it respond to a
    click, show a hand cursor, and the card lights up on hover."""
    resting = [frame.cget("fg_color")]

    def enter(_event) -> None:
        resting[0] = frame.cget("fg_color")  # e.g. white, or the "selected" colour
        frame.configure(fg_color=COLORS["surface_hover"])

    def leave(_event) -> None:
        # Only undo our own hover colour: if a click meanwhile changed the colour (a
        # row was selected), keep that.
        if frame.cget("fg_color") == COLORS["surface_hover"]:
            frame.configure(fg_color=resting[0])

    def bind(widget) -> None:
        widget.bind("<Button-1>", lambda _e: command(), add="+")
        widget.bind("<Enter>", enter, add="+")
        widget.bind("<Leave>", leave, add="+")
        try:
            widget.configure(cursor="hand2")
        except (ValueError, Exception):  # some CTk widgets don't accept a cursor option
            pass
        for child in widget.winfo_children():
            bind(child)

    bind(frame)


def clear(container) -> None:
    for child in container.winfo_children():
        child.destroy()


class QuantityStepper(ctk.CTkFrame):
    """[ - ]  3  [ + ]  — calls on_change(new_value) when a button is pressed."""

    def __init__(self, parent, value: int, on_change: Callable[[int], None],
                 minimum: int = 1, maximum: int = 99) -> None:
        super().__init__(parent, fg_color="transparent")
        self._value, self._min, self._max = value, minimum, maximum
        self._on_change = on_change
        # Round +/- buttons like Flipkart's cart (the one place it uses circles).
        style = dict(width=28, height=28, corner_radius=14, font=theme.font(15, "bold"),
                     fg_color=COLORS["surface"], hover_color=COLORS["surface_hover"],
                     border_width=1, border_color=COLORS["border"],
                     text_color=COLORS["text"], text_color_disabled=COLORS["disabled"])
        self._minus = ctk.CTkButton(self, text="−", command=lambda: self._step(-1), **style)
        self._label = ctk.CTkLabel(self, text=str(value), width=44, height=28,
                                   font=theme.font(13, "bold"), text_color=COLORS["text"],
                                   fg_color=COLORS["surface"], corner_radius=CORNER_RADIUS)
        self._plus = ctk.CTkButton(self, text="+", command=lambda: self._step(1), **style)
        self._minus.pack(side="left")
        self._label.pack(side="left", padx=PAD_S)
        self._plus.pack(side="left")
        self._refresh()

    @property
    def value(self) -> int:
        return self._value

    def _step(self, delta: int) -> None:
        new = min(max(self._value + delta, self._min), self._max)
        if new != self._value:
            self._value = new
            self._refresh()
            self._on_change(new)

    def _refresh(self) -> None:
        self._label.configure(text=str(self._value))
        self._minus.configure(state="normal" if self._value > self._min else "disabled")
        self._plus.configure(state="normal" if self._value < self._max else "disabled")

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._refresh()
        else:
            self._minus.configure(state="disabled")
            self._plus.configure(state="disabled")


def form_entry(parent, placeholder: str, show: str | None = None) -> ctk.CTkEntry:
    return ctk.CTkEntry(parent, placeholder_text=placeholder, show=show, height=38,
                        corner_radius=CORNER_RADIUS, font=theme.body_font(), border_width=1,
                        fg_color=COLORS["surface"], border_color=COLORS["border"],
                        text_color=COLORS["text"], placeholder_text_color=COLORS["text_muted"])


def field_label(parent, text: str) -> ctk.CTkLabel:
    """Small bold caption shown above a form field."""
    return label(parent, text, size=12, color=COLORS["text_muted"])


def link_button(parent, text: str, command: Callable[[], None]) -> ctk.CTkButton:
    """A text-only button that looks like a link."""
    return ctk.CTkButton(parent, text=text, command=command, fg_color="transparent",
                         hover_color=COLORS["surface_hover"], text_color=COLORS["accent"],
                         font=theme.font(13, "bold"), height=26, width=0,
                         corner_radius=CORNER_RADIUS)

