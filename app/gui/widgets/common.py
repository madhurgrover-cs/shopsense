"""Small reusable widgets: pills, cards, clickable areas, quantity stepper."""

from collections.abc import Callable

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, CORNER_RADIUS, PAD_M, PAD_S


def pill(parent, text: str, color: str) -> ctk.CTkLabel:
    """A small rounded label, e.g. a "Positive" badge or a "delivered" status."""
    return ctk.CTkLabel(parent, text=f" {text} ", font=theme.font(12, "bold"),
                        text_color=COLORS["bg"], fg_color=color, corner_radius=8, height=22)


def card(parent, **kwargs) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=COLORS["surface"], corner_radius=CORNER_RADIUS,
                        **kwargs)


def label(parent, text: str = "", size: int = 14, weight: str = "normal",
          color: str | None = None, **kwargs) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, font=theme.font(size, weight),
                        text_color=color or COLORS["text"], anchor="w", justify="left",
                        **kwargs)


def muted(parent, text: str = "", size: int = 13, **kwargs) -> ctk.CTkLabel:
    return label(parent, text, size=size, color=COLORS["text_muted"], **kwargs)


def section_title(parent, text: str) -> ctk.CTkLabel:
    return label(parent, text, size=16, weight="bold")


def empty_state(parent, text: str) -> ctk.CTkLabel:
    return muted(parent, text, size=14)


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
    normal = frame.cget("fg_color")

    def bind(widget) -> None:
        widget.bind("<Button-1>", lambda _e: command(), add="+")
        widget.bind("<Enter>", lambda _e: frame.configure(fg_color=COLORS["surface_hover"]),
                    add="+")
        widget.bind("<Leave>", lambda _e: frame.configure(fg_color=normal), add="+")
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
        style = dict(width=32, height=32, corner_radius=8, font=theme.font(16, "bold"),
                     fg_color=COLORS["surface_hover"], hover_color=COLORS["border"],
                     text_color=COLORS["text"])
        self._minus = ctk.CTkButton(self, text="−", command=lambda: self._step(-1), **style)
        self._label = ctk.CTkLabel(self, text=str(value), width=40, font=theme.font(14, "bold"),
                                   text_color=COLORS["text"])
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
    return ctk.CTkEntry(parent, placeholder_text=placeholder, show=show, height=40,
                        corner_radius=CORNER_RADIUS, font=theme.body_font(),
                        fg_color=COLORS["bg"], border_color=COLORS["border"],
                        text_color=COLORS["text"])


def field_label(parent, text: str) -> ctk.CTkLabel:
    """Small bold caption shown above a form field."""
    return label(parent, text, size=12, weight="bold", color=COLORS["text_muted"])


def link_button(parent, text: str, command: Callable[[], None]) -> ctk.CTkButton:
    """A text-only button that looks like a link."""
    return ctk.CTkButton(parent, text=text, command=command, fg_color="transparent",
                         hover_color=COLORS["surface"], text_color=COLORS["accent"],
                         font=theme.font(13), height=28, width=0)

