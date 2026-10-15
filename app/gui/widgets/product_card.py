"""A clickable product card: name, category, price, rating, sentiment badge, stock."""

from collections.abc import Callable

import customtkinter as ctk

from app.gui import formatting as fmt
from app.gui.theme import COLORS, PAD_M, PAD_S
from app.gui.widgets.common import auto_wrap, card, label, make_clickable, muted, pill
from app.services.dto import ProductSummary


class ProductCard(ctk.CTkFrame):
    def __init__(self, parent, product: ProductSummary, on_open: Callable[[int], None],
                 compact: bool = False) -> None:
        super().__init__(parent, fg_color="transparent")
        box = card(self)
        box.pack(fill="both", expand=True)
        name = label(box, product.name, size=13 if compact else 14, weight="bold",
                     wraplength=180)
        name.pack(fill="x", padx=PAD_M, pady=(PAD_M, 0))
        auto_wrap(name, box, padding=2 * PAD_M)
        category = muted(box, product.category, size=12, wraplength=180)
        category.pack(fill="x", padx=PAD_M)
        auto_wrap(category, box, padding=2 * PAD_M)
        label(box, fmt.inr(product.price), size=16 if not compact else 14,
              weight="bold").pack(fill="x", padx=PAD_M, pady=(PAD_S, 0))

        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=PAD_M, pady=(2, 0))
        muted(row, fmt.rating(product.avg_rating, product.review_count), size=12).pack(side="left")
        if product.sentiment_badge:
            pill(row, product.sentiment_badge,
                 fmt.BADGE_COLORS[product.sentiment_badge]).pack(side="right")

        if not compact:
            text, color = fmt.stock_text(product.stock, product.is_active)
            label(box, text, size=12, color=color).pack(fill="x", padx=PAD_M, pady=(2, 0))
        ctk.CTkFrame(box, height=PAD_S, fg_color="transparent").pack()

        make_clickable(box, lambda: on_open(product.id))
