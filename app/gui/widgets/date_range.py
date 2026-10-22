"""DateRangeBar: "From [2026-09-17]  To [2026-10-16]  [7 days] [30 days] [90 days] [All]".

CustomTkinter has no calendar picker, so dates are typed as YYYY-MM-DD; the preset
buttons fill both boxes for the common cases. The bar does not check the dates: the
service does, and its ValidationError explains what is wrong ("Start date must be on
or before the end date.").
"""

from collections.abc import Callable
from datetime import timedelta

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, CORNER_RADIUS, PAD_S
from app.gui.widgets.common import muted
from app.services.validation import today

PRESET_DAYS = {"7 days": 7, "30 days": 30, "90 days": 90}
ALL = "All"


class DateRangeBar(ctk.CTkFrame):
    def __init__(self, parent, on_change: Callable[[], None], default_days: int = 30,
                 allow_all: bool = False) -> None:
        """on_change(): called after a preset is clicked or Enter is pressed in a box.
        allow_all adds an "All" preset that empties both boxes (= no date filter)."""
        super().__init__(parent, fg_color="transparent")
        self._on_change = on_change
        self._from = self._entry()
        self._to = self._entry()
        muted(self, "From").pack(side="left", padx=(0, 4))
        self._from.pack(side="left")
        muted(self, "To").pack(side="left", padx=(PAD_S, 4))
        self._to.pack(side="left")

        presets = list(PRESET_DAYS) + ([ALL] if allow_all else [])
        self._presets = ctk.CTkSegmentedButton(
            self, values=presets, command=self._preset, font=theme.font(13),
            **theme.segmented_style())
        self._presets.pack(side="left", padx=(PAD_S + 4, 0))
        default = next((k for k, v in PRESET_DAYS.items() if v == default_days), None)
        if default:
            self._presets.set(default)
        self._fill(default_days)

    def _entry(self) -> ctk.CTkEntry:
        entry = ctk.CTkEntry(self, width=118, height=34, corner_radius=CORNER_RADIUS, border_width=1,
                             font=theme.font(13), fg_color=COLORS["surface"],
                             border_color=COLORS["border"], text_color=COLORS["text"],
                             placeholder_text="YYYY-MM-DD")
        entry.bind("<Return>", lambda _e: self._typed())
        return entry

    def _fill(self, days: int | None) -> None:
        for entry in (self._from, self._to):
            entry.delete(0, "end")
        if days is not None:
            end = today()
            self._from.insert(0, (end - timedelta(days=days - 1)).isoformat())
            self._to.insert(0, end.isoformat())

    def _preset(self, name: str) -> None:
        self._fill(PRESET_DAYS.get(name))  # None for "All": empty boxes
        self._on_change()

    def _typed(self) -> None:
        self._presets.set("")  # typed dates no longer match a preset button
        self._on_change()

    def get(self) -> tuple[str | None, str | None]:
        """(from, to) as typed; None for an empty box."""
        return (self._from.get().strip() or None, self._to.get().strip() or None)

    def set(self, start: str, end: str) -> None:
        """Type dates into both boxes (used by tests)."""
        self._presets.set("")
        for entry, text in ((self._from, start), (self._to, end)):
            entry.delete(0, "end")
            entry.insert(0, text)
