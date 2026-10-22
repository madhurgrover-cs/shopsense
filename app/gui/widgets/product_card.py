"""A clickable product tile, Flipkart style: a soft category tile with the category's
icon (instead of a photo), then name, green rating pill, bold price, and a small
line about what reviewers think."""

from collections.abc import Callable

import customtkinter as ctk

from app.gui import formatting as fmt
from app.gui.theme import COLORS, CORNER_RADIUS, PAD_M, PAD_S
from app.gui.widgets.common import (
    auto_wrap, category_tile, label, make_clickable, rating_pill,
)
from app.services.dto import ProductSummary

# Names are cut to about two lines, so every tile in a row has the same shape.
MAX_NAME = 52
MAX_NAME_COMPACT = 40


def short_name(name: str, limit: int) -> str:
    return name if len(name) <= limit else name[:limit - 1].rstrip() + "…"


class ProductCard(ctk.CTkFrame):
    def __init__(self, parent, product: ProductSummary, on_open: Callable[[int], None],
                 compact: bool = False) -> None:
        super().__init__(parent, fg_color=COLORS["surface"], corner_radius=CORNER_RADIUS,
                         border_width=1, border_color=COLORS["border"])
        tile = category_tile(self, product.category, height=60 if compact else 92,
                             icon_size=26 if compact else 38)
        tile.pack(fill="x", padx=PAD_M, pady=(PAD_M, PAD_S))

        name = label(self, short_name(product.name, MAX_NAME_COMPACT if compact else MAX_NAME),
                     size=13, wraplength=180)
        name.pack(fill="x", padx=PAD_M)
        auto_wrap(name, self, padding=2 * PAD_M)
        rating_pill(self, product.avg_rating, product.review_count).pack(
            fill="x", padx=PAD_M, pady=(4, 0))
        label(self, fmt.inr(product.price), size=15, weight="bold").pack(
            fill="x", padx=PAD_M, pady=(4, 0))
        if product.sentiment_badge:
            label(self, fmt.sentiment_text(product.sentiment_badge), size=11,
                  color=fmt.BADGE_COLORS[product.sentiment_badge]).pack(fill="x", padx=PAD_M)
        if not compact:
            text, color = fmt.stock_text(product.stock, product.is_active)
            label(self, text, size=11, color=color).pack(fill="x", padx=PAD_M)
        ctk.CTkFrame(self, height=PAD_S, width=1, fg_color="transparent").pack()

        make_clickable(self, lambda: on_open(product.id))
