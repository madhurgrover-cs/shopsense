"""DataTable: a light, dense, sortable table for the admin screens.

CustomTkinter has no table widget, so this wraps Tk's ttk.Treeview. Treeview is also
the right tool for the job here: it draws hundreds of rows (500 orders) instantly,
where one CTk frame per row would take seconds and lots of memory on a 4 GB laptop.

Usage:
    table = DataTable(parent, [
        Column("ID", 60, lambda p: p.id, anchor="e"),
        Column("Name", 300, lambda p: p.name),
        Column("Price", 110, lambda p: fmt.inr(p.price), sort=lambda p: p.price, anchor="e"),
    ], on_select=..., on_open=...)
    table.set_items(products, key=lambda p: p.id)

Each column turns an item into display text; `sort` (optional) gives the value to sort
by when its header is clicked (default: the display text). Click again to reverse.

Light / dark mode: ttk knows nothing about CTk's appearance mode and takes single
colour strings, so the style is built from theme.resolve(...) and rebuilt whenever the
mode changes (_set_appearance_mode below).

Column widths are PROPORTIONS: the table always fills its width exactly, sharing it
out in the ratio of the given widths (re-done whenever the window is resized). So a
table never runs off the right edge, at any window size or display scaling.
"""

import tkinter.font as tkfont
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk
from typing import Any

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS

STYLE = "ShopSense.Treeview"
ROW_COLORS = ("text_muted", "danger", "warning", "success")  # allowed row_color keys


@dataclass
class Column:
    title: str
    width: int                               # relative width (share of the table)
    value: Callable[[Any], Any]              # item -> text shown
    sort: Callable[[Any], Any] | None = None  # item -> sort key (default: shown text)
    anchor: str = "w"                        # "w" left, "e" right (numbers), "center"


def _configure_style(widget) -> int:
    """Colours for the current mode on every Treeview using STYLE (ttk styles are shared
    by all tables, so restyling once covers them all). Returns the row height in pixels."""
    c = {key: theme.resolve(value) for key, value in COLORS.items()}
    style = ttk.Style(widget)
    style.theme_use("clam")  # the default Windows theme ignores background colours
    body = tkfont.Font(widget, family=theme.font_family(), size=10)
    head = tkfont.Font(widget, family=theme.font_family(), size=9, weight="bold")
    # The row height is in real pixels while font sizes are in points, which Tk scales
    # with the screen's DPI; measuring the font keeps rows right at 100 % and 150 %.
    # +10 keeps rows dense, like a seller dashboard.
    row_height = body.metrics("linespace") + 10
    style.configure(STYLE, background=c["surface"], fieldbackground=c["surface"],
                    foreground=c["text"], rowheight=row_height, font=body,
                    borderwidth=0, relief="flat")
    # Selected row: a blue tint with blue text (a solid blue bar would be too loud).
    style.map(STYLE, background=[("selected", c["selected_nav"])],
              foreground=[("selected", c["accent"])])
    style.configure(f"{STYLE}.Heading", background=c["surface_hover"],
                    foreground=c["text_muted"], font=head, relief="flat",
                    borderwidth=0, padding=(8, 7))
    style.map(f"{STYLE}.Heading", background=[("active", c["border"])])
    style.layout(STYLE, [("Treeview.treearea", {"sticky": "nswe"})])  # no inner border
    return row_height


class DataTable(ctk.CTkFrame):
    def __init__(self, parent, columns: list[Column],
                 on_select: Callable[[Any], None] | None = None,
                 on_open: Callable[[Any], None] | None = None,
                 row_color: Callable[[Any], str | None] | None = None,
                 empty_text: str = "Nothing to show.") -> None:
        """on_select(item): a row was selected. on_open(item): double-click or Enter.
        row_color(item): a COLORS key for the row's text (e.g. "text_muted"), or None."""
        super().__init__(parent, fg_color=COLORS["surface"], corner_radius=theme.CORNER_RADIUS,
                         border_width=1, border_color=COLORS["border"])
        self._columns = columns
        self._on_select, self._on_open, self._row_color = on_select, on_open, row_color
        self._items: dict[str, Any] = {}
        self._order: list[str] = []
        self._sorted_by: tuple[int, bool] | None = None  # (column index, descending)

        _configure_style(self)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        ids = [f"c{i}" for i in range(len(columns))]
        self.tree = ttk.Treeview(self, columns=ids, show="headings", style=STYLE,
                                 selectmode="browse")
        for i, (cid, column) in enumerate(zip(ids, columns)):
            self.tree.heading(cid, text=column.title, anchor=column.anchor,
                              command=lambda i=i: self.sort_by(i))
            self.tree.column(cid, width=column.width, minwidth=30, anchor=column.anchor,
                             stretch=False)
        self._color_tags()

        scrollbar = ctk.CTkScrollbar(self, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=6)
        self._empty = ctk.CTkLabel(self, text=empty_text, font=theme.body_font(),
                                   text_color=COLORS["text_muted"])

        self.tree.bind("<Configure>", self._fit_columns)
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.tree.bind("<Double-1>", self._opened)
        self.tree.bind("<Return>", self._opened)

    def _color_tags(self) -> None:
        """Row text colours (row_color keys) for the current mode."""
        for name in ROW_COLORS:
            self.tree.tag_configure(name, foreground=theme.resolve(COLORS[name]))

    def _set_appearance_mode(self, mode_string: str) -> None:
        """CustomTkinter calls this on every CTk widget when the light / dark mode
        changes. The CTk parts (frame, scrollbar, label) redraw in super(); the ttk
        Treeview inside needs its colours re-applied by hand."""
        super()._set_appearance_mode(mode_string)
        _configure_style(self)
        self._color_tags()

    def _fit_columns(self, event) -> None:
        """Share the table's current width out between the columns (see top of file)."""
        total = sum(c.width for c in self._columns)
        widths = [int(event.width * c.width / total) for c in self._columns]
        widths[-1] += event.width - sum(widths) - 2  # rounding leftovers; 2 px for borders
        for i, width in enumerate(widths):
            self.tree.column(f"c{i}", width=max(width, 30))

    # ------------------------------------------------------------------ data

    def set_items(self, items: list, key: Callable[[Any], Any]) -> None:
        """Replace all rows. The selection is kept if that item is still there."""
        selected = self.selected_key
        self._items = {str(key(item)): item for item in items}
        self._order = list(self._items)
        if self._sorted_by is not None:
            self._apply_sort()
        self._redraw()
        if selected is not None and selected in self._items:
            self.select(selected)
        if items:
            self._empty.place_forget()
        else:
            self._empty.place(relx=0.5, rely=0.3, anchor="center")

    def _redraw(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for iid in self._order:
            item = self._items[iid]
            values = [self._text(column.value(item)) for column in self._columns]
            color = self._row_color(item) if self._row_color else None
            self.tree.insert("", "end", iid=iid, values=values, tags=(color,) if color else ())

    @staticmethod
    def _text(value) -> str:
        return "" if value is None else str(value)

    @property
    def items(self) -> list:
        """Items in the order shown."""
        return [self._items[iid] for iid in self._order]

    # ------------------------------------------------------------------ selection

    @property
    def selected_key(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    @property
    def selected(self):
        key = self.selected_key
        return self._items.get(key) if key is not None else None

    def select(self, key) -> None:
        key = str(key)
        if key in self._items:
            self.tree.selection_set(key)
            self.tree.see(key)

    def _selected(self, _event=None) -> None:
        if self._on_select and self.selected is not None:
            self._on_select(self.selected)

    def _opened(self, _event=None) -> None:
        if self._on_open and self.selected is not None:
            self._on_open(self.selected)

    # ------------------------------------------------------------------ sorting

    def sort_by(self, index: int) -> None:
        """Header click: sort by this column; clicking the same column again reverses."""
        descending = self._sorted_by == (index, False)
        self._sorted_by = (index, descending)
        self._apply_sort()
        self._redraw()
        for i, column in enumerate(self._columns):
            arrow = (" ▼" if descending else " ▲") if i == index else ""
            self.tree.heading(f"c{i}", text=column.title + arrow)

    def _apply_sort(self) -> None:
        index, descending = self._sorted_by
        column = self._columns[index]
        key = column.sort or (lambda item: self._text(column.value(item)).lower())

        values = {iid: key(self._items[iid]) for iid in self._order}
        present = [iid for iid in self._order if values[iid] is not None]
        missing = [iid for iid in self._order if values[iid] is None]
        present.sort(key=values.__getitem__, reverse=descending)
        self._order = present + missing  # empty values always last, either direction
