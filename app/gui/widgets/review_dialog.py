"""Popup for writing a review: 1-5 stars and an optional comment."""

from collections.abc import Callable

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, CORNER_RADIUS, PAD_L, PAD_M, PAD_S
from app.gui.widgets.common import label, muted


class ReviewDialog(ctk.CTkToplevel):
    def __init__(self, parent, product_name: str,
                 on_submit: Callable[[int, str], None]) -> None:
        super().__init__(parent)
        self.title("Write a review")
        self.configure(fg_color=COLORS["surface"])
        self.resizable(False, False)
        self.transient(parent)
        self._on_submit = on_submit
        self._rating = 0

        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(padx=PAD_L, pady=PAD_L, fill="both", expand=True)
        label(box, "Write a review", size=18, weight="bold").pack(fill="x")
        muted(box, product_name, wraplength=420).pack(fill="x", pady=(2, PAD_M))

        label(box, "Your rating", size=13, weight="bold").pack(fill="x")
        stars = ctk.CTkFrame(box, fg_color="transparent")
        stars.pack(fill="x", pady=(2, PAD_M))
        self._star_buttons = []
        for value in range(1, 6):
            button = ctk.CTkButton(stars, text="☆", width=40, height=40,
                                   font=theme.font(24), fg_color="transparent",
                                   hover_color=COLORS["surface_hover"],
                                   text_color=COLORS["warning"],
                                   command=lambda v=value: self._set_rating(v))
            button.pack(side="left")
            self._star_buttons.append(button)
        self._rating_text = muted(stars, "Tap a star")
        self._rating_text.pack(side="left", padx=PAD_M)

        label(box, "Comment (optional)", size=13, weight="bold").pack(fill="x")
        self._comment = ctk.CTkTextbox(box, width=440, height=120, corner_radius=CORNER_RADIUS,
                                       font=theme.body_font(), fg_color=COLORS["bg"],
                                       border_color=COLORS["border"], border_width=1,
                                       text_color=COLORS["text"], wrap="word")
        self._comment.pack(fill="x", pady=(4, PAD_M))

        buttons = ctk.CTkFrame(box, fg_color="transparent")
        buttons.pack(fill="x")
        self._submit = ctk.CTkButton(buttons, text="Submit review", width=150,
                                     command=self._submit_clicked, state="disabled",
                                     **theme.primary_button_style())
        self._submit.pack(side="right")
        ctk.CTkButton(buttons, text="Cancel", width=100, command=self.destroy,
                      **theme.secondary_button_style()).pack(side="right", padx=PAD_S)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(50, self._make_modal)

    def _make_modal(self) -> None:
        if self.winfo_exists():
            self.grab_set()
            self._comment.focus_set()

    def _set_rating(self, value: int) -> None:
        self._rating = value
        for index, button in enumerate(self._star_buttons, start=1):
            button.configure(text="★" if index <= value else "☆")
        self._rating_text.configure(text=["", "Terrible", "Poor", "Okay", "Good",
                                          "Excellent"][value])
        self._submit.configure(state="normal")

    def _submit_clicked(self) -> None:
        self._submit.configure(state="disabled")
        self._on_submit(self._rating, self._comment.get("1.0", "end").strip())

    def submission_failed(self) -> None:
        """Called by the owner if saving failed, so the user can try again."""
        if self.winfo_exists():
            self._submit.configure(state="normal")
