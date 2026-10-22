"""Admin: "Ask your data". Type a question in plain English; Gemini writes the SQL,
ask_data_service checks and runs it read-only, and this screen shows:

    [ question .......................................... ] [ Ask ]
    Try: [ Which category made...   ] [ Top 5 customers by...    ]
         [ How many orders were...  ] [ Which products have no...]
    +--------------------------------------------------------------+
    | One-sentence answer (or what went wrong)                      |
    | 12 rows                                    Show SQL ▸         |
    | (the SQL, when expanded)                                     |
    +--------------------------------------------------------------+
    | result table                                                  |

The SQL starts collapsed: most admins only want the answer, but it's there to check
how the answer was worked out (and to see which query was blocked, if one was).
"""

import gc
from decimal import Decimal

import customtkinter as ctk

from app.gui import theme
from app.gui.screens.admin.common import button, set_enabled, toolbar
from app.gui.screens.admin.reports import cell_text
from app.gui.screens.base import Screen
from app.gui.theme import COLORS, CORNER_RADIUS, PAD_L, PAD_M, PAD_S, PAD_XL
from app.gui.widgets.common import auto_wrap, card, label, link_button, muted
from app.gui.widgets.table import Column, DataTable
from app.services import ask_data_service
from app.services.dto import DataAnswer
from app.services.error_messages import friendly_error

SQL_FONT = ("Consolas", 12)  # monospace, so the SQL's indentation lines up


class AskDataScreen(Screen):
    title = "Ask your data"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self.answer: DataAnswer | None = None
        self.table: DataTable | None = None
        self._sql_open = False
        self._asking = False

        bar = toolbar(self)
        self._question = ctk.CTkEntry(
            bar, height=34, corner_radius=CORNER_RADIUS, font=theme.body_font(), border_width=1,
            placeholder_text="Ask a question about the store, e.g. "
                             "\"What was the revenue in each of the last 6 months?\"",
            fg_color=COLORS["surface"], border_color=COLORS["border"],
            text_color=COLORS["text"])
        self._question.pack(side="left", fill="x", expand=True)
        self._question.bind("<Return>", lambda _e: self.ask())
        self._ask = button(bar, "Ask", self.ask, kind="primary", width=100)
        self._ask.pack(side="left", padx=(PAD_S, 0))

        # The example questions, as a 2 x 2 grid of buttons (one row would be too wide).
        examples = ctk.CTkFrame(self, fg_color="transparent")
        examples.pack(fill="x", padx=PAD_XL, pady=(0, PAD_M))
        muted(examples, "Try:", size=12).grid(row=0, column=0, sticky="nw",
                                              padx=(0, PAD_S), pady=(6, 0))
        self._examples = []
        for i, text in enumerate(ask_data_service.EXAMPLE_QUESTIONS):
            example = button(examples, text, lambda t=text: self._use_example(t), width=0)
            example.grid(row=i // 2, column=1 + i % 2, sticky="ew", padx=(0, PAD_S),
                         pady=(0, PAD_S))
            self._examples.append(example)
        examples.grid_columnconfigure((1, 2), weight=1, uniform="examples")

        # Answer card: summary, row count, collapsible SQL.
        self._card = card(self)
        self._card.pack(fill="x", padx=PAD_XL, pady=(0, PAD_M))
        self._summary = label(self._card, "Answers come from the live database. The AI "
                              "only writes a read-only query; nothing can be changed here.",
                              size=15, weight="bold", color=COLORS["text_muted"],
                              wraplength=700)
        self._summary.pack(fill="x", padx=PAD_L, pady=(PAD_M, 2))
        auto_wrap(self._summary, self._card, padding=2 * PAD_L)
        meta = ctk.CTkFrame(self._card, fg_color="transparent")
        meta.pack(fill="x", padx=PAD_L, pady=(0, PAD_S))
        self._meta = muted(meta, "", size=12)
        self._meta.pack(side="left")
        self._sql_toggle = link_button(meta, "Show SQL ▸", self.toggle_sql)
        self._sql = ctk.CTkTextbox(self._card, height=150, font=SQL_FONT, wrap="none",
                                   fg_color=COLORS["bg"], text_color=COLORS["text"],
                                   border_color=COLORS["border"], border_width=1,
                                   corner_radius=CORNER_RADIUS)

        self._table_area = ctk.CTkFrame(self, fg_color="transparent")
        self._table_area.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_L))

    def on_show(self, **kwargs) -> None:
        self._question.focus_set()

    # ------------------------------------------------------------------ asking

    def _use_example(self, text: str) -> None:
        if self._asking:
            return  # keep the box showing the question being answered
        self._question.delete(0, "end")
        self._question.insert(0, text)
        self.ask()

    def ask(self) -> None:
        question = self._question.get().strip()
        if self._asking:
            return  # one question at a time (e.g. Enter pressed twice)
        if not question:
            self._show_problem("Type a question first.", None, title=None)
            return
        self._asking = True
        self._set_buttons_enabled(False)
        self.app.tasks.run(ask_data_service.ask, self.app.user, question,
                           on_success=self._show_answer, on_error=self._show_error,
                           message="Asking the AI and running the query...")

    # ------------------------------------------------------------------ display

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for widget in [self._ask, *self._examples]:
            set_enabled(widget, enabled)

    def _done(self) -> None:
        self._asking = False
        self._set_buttons_enabled(True)

    def _show_answer(self, answer: DataAnswer) -> None:
        self._done()
        self.answer = answer
        self._summary.configure(text=answer.summary, text_color=COLORS["text"])
        self._meta.configure(text=f"{answer.row_count_text}  ·  AI-written query, "
                                  "run read-only")
        self._set_sql(answer.sql)
        self._build_table(answer.columns, answer.rows)

    def _show_error(self, error: BaseException) -> None:
        """Errors are shown in the answer card (not a popup), with the SQL if there
        was one: for a blocked query, seeing it explains why it was blocked."""
        self._done()
        info = friendly_error(error)
        self._show_problem(info.message, getattr(error, "sql", None), title=info.title)

    def _show_problem(self, message: str, sql: str | None, title: str | None) -> None:
        self.answer = None
        text = f"{title}: {message}" if title else message
        self._summary.configure(text=text, text_color=COLORS["danger"])
        self._meta.configure(text="")
        self._set_sql(sql)
        self._build_table([], [])

    def _set_sql(self, sql: str | None) -> None:
        self._sql.configure(state="normal")
        self._sql.delete("1.0", "end")
        self._sql.insert("1.0", sql or "")
        self._sql.configure(state="disabled")  # read-only, but text can still be copied
        if sql:
            self._sql_toggle.pack(side="right")
        else:
            self._sql_toggle.pack_forget()
            self._set_sql_open(False)

    def toggle_sql(self) -> None:
        self._set_sql_open(not self._sql_open)

    def _set_sql_open(self, is_open: bool) -> None:
        self._sql_open = is_open
        self._sql_toggle.configure(text="Hide SQL ▾" if is_open else "Show SQL ▸")
        if is_open:
            self._sql.pack(fill="x", padx=PAD_L, pady=(0, PAD_M))
        else:
            self._sql.pack_forget()

    def _build_table(self, columns: list[str], rows: list[tuple]) -> None:
        # Every question has different columns, so the table is rebuilt each time.
        if self.table is not None:
            self.table.destroy()
            self.table = None
            gc.collect()  # free the old table on the main thread (see app._set_screens)
        if not columns:
            return
        table_columns = []
        for i, name in enumerate(columns):
            sample = [r[i] for r in rows[:50] if r[i] is not None]
            numeric = bool(sample) and all(
                isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in sample)
            longest = max([len(name)] + [len(cell_text(v, False)) for v in sample])
            table_columns.append(Column(
                name, min(max(longest * 9, 70), 360),
                lambda pair, i=i: cell_text(pair[1][i], False),
                sort=lambda pair, i=i: pair[1][i], anchor="e" if numeric else "w"))
        self.table = DataTable(self._table_area, table_columns,
                               empty_text="No rows matched.")
        self.table.pack(fill="both", expand=True)
        # Items are (row number, row) pairs: rows aren't guaranteed unique on their own.
        self.table.set_items(list(enumerate(rows)), key=lambda pair: pair[0])
