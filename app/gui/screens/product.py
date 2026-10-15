"""Product page: details, stock, Add to cart, recommendations and reviews."""

from dataclasses import dataclass

import customtkinter as ctk

from app.gui import formatting as fmt
from app.gui import theme
from app.gui.screens.base import Screen
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S, PAD_XL
from app.gui.widgets.common import (
    QuantityStepper, auto_wrap, card, clear, empty_state, label, link_button, muted, pill,
    section_title,
)
from app.gui.widgets.product_card import ProductCard
from app.services import cart_service, catalog_service, review_service
from app.services.dto import ProductDetail, ProductSentiment, ProductSummary, ReviewInfo

RECOMMENDATIONS = 5


@dataclass
class ProductPage:
    """Everything the page shows, loaded together in ONE background task."""
    product: ProductDetail
    sentiment: ProductSentiment
    reviews: list[ReviewInfo]
    bought_together: list[ProductSummary]
    similar: list[ProductSummary]


def load_product_page(product_id: int) -> ProductPage:
    """Runs in the background thread: five service calls, one after another."""
    return ProductPage(
        product=catalog_service.get_product_detail(product_id),
        sentiment=review_service.get_product_sentiment(product_id),
        reviews=review_service.list_product_reviews(product_id),
        bought_together=catalog_service.frequently_bought_together(product_id, RECOMMENDATIONS),
        similar=catalog_service.similar_products(product_id, RECOMMENDATIONS),
    )


class ProductScreen(Screen):
    title = "Product"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self._back_to = "shop"
        self._product_id: int | None = None
        self._request = 0

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=PAD_XL - PAD_S, pady=(0, PAD_S))
        link_button(top, "← Back", lambda: self.app.navigate(self._back_to)).pack(side="left")

        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.pack(fill="both", expand=True, padx=PAD_L, pady=(0, PAD_L))

    def on_show(self, product_id: int | None = None, back_to: str | None = None,
                **kwargs) -> None:
        if back_to:
            self._back_to = back_to
        if product_id is None:
            return
        self._product_id = product_id
        self._request += 1
        request = self._request
        clear(self._body)
        self.app.tasks.run(load_product_page, product_id, message="Loading product...",
                           on_success=lambda page: self._render(request, page))

    # ------------------------------------------------------------------ rendering

    def _render(self, request: int, page: ProductPage) -> None:
        if request != self._request:
            return
        clear(self._body)
        self._body._parent_canvas.yview_moveto(0)
        self._render_details(page)
        self._render_row("Frequently bought together", page.bought_together,
                         "Not enough orders yet to show products bought with this one.")
        self._render_row("Similar products", page.similar,
                         "No similar products found.")
        self._render_reviews(page)

    def _render_details(self, page: ProductPage) -> None:
        p = page.product
        box = card(self._body)
        box.pack(fill="x", padx=PAD_S, pady=(0, PAD_M))
        box.grid_columnconfigure(0, weight=1)

        info = ctk.CTkFrame(box, fg_color="transparent")
        info.grid(row=0, column=0, sticky="nsew", padx=PAD_L, pady=PAD_L)
        muted(info, p.category, size=13).pack(fill="x")
        name = label(info, p.name, size=24, weight="bold", wraplength=500)
        name.pack(fill="x", pady=(2, PAD_S))
        auto_wrap(name, info)

        meta = ctk.CTkFrame(info, fg_color="transparent")
        meta.pack(fill="x")
        muted(meta, fmt.rating(p.avg_rating, p.review_count), size=14).pack(side="left")
        if page.sentiment.badge:
            pill(meta, f"Reviews: {page.sentiment.badge}",
                 fmt.BADGE_COLORS[page.sentiment.badge]).pack(side="left", padx=PAD_M)

        description = label(info, p.description, size=14, color=COLORS["text_muted"],
                            wraplength=500)
        description.pack(fill="x", pady=(PAD_M, 0))
        auto_wrap(description, info)

        # Right-hand buy panel.
        buy = ctk.CTkFrame(box, fg_color=COLORS["bg"], corner_radius=theme.CORNER_RADIUS)
        buy.grid(row=0, column=1, sticky="n", padx=PAD_L, pady=PAD_L)
        label(buy, fmt.inr(p.price), size=26, weight="bold").pack(
            fill="x", padx=PAD_L, pady=(PAD_L, 2))
        text, color = fmt.stock_text(p.stock, p.is_active)
        label(buy, text, size=13, color=color).pack(fill="x", padx=PAD_L, pady=(0, PAD_M))

        can_buy = p.is_active and p.stock > 0
        stepper = QuantityStepper(buy, 1, on_change=lambda _v: None,
                                  maximum=max(1, min(p.stock, 10)))
        stepper.pack(anchor="w", padx=PAD_L)
        stepper.set_enabled(can_buy)
        button = ctk.CTkButton(buy, text="Add to cart", width=220,
                               command=lambda: self._add_to_cart(p, stepper.value, button),
                               **theme.primary_button_style())
        button.pack(padx=PAD_L, pady=(PAD_M, PAD_L))
        if not can_buy:
            button.configure(state="disabled",
                             text="Unavailable" if not p.is_active else "Out of stock")

    def _render_row(self, title: str, products: list[ProductSummary], empty: str) -> None:
        section_title(self._body, title).pack(fill="x", padx=PAD_S, pady=(PAD_S, PAD_S))
        row = ctk.CTkFrame(self._body, fg_color="transparent")
        row.pack(fill="x", pady=(0, PAD_M))
        if not products:
            empty_state(row, empty).pack(anchor="w", padx=PAD_S)
            return
        for column in range(RECOMMENDATIONS):
            row.grid_columnconfigure(column, weight=1, uniform="rec")
        for index, product in enumerate(products):
            ProductCard(row, product, compact=True, on_open=self._open_other).grid(
                row=0, column=index, sticky="nsew", padx=PAD_S)

    def _render_reviews(self, page: ProductPage) -> None:
        section_title(self._body, f"Reviews ({len(page.reviews)})").pack(
            fill="x", padx=PAD_S, pady=(PAD_S, PAD_S))
        if not page.reviews:
            empty_state(self._body, "No reviews yet. Customers can review a product "
                                    "after it is delivered.").pack(fill="x", padx=PAD_S)
            return
        for review in page.reviews:
            box = card(self._body)
            box.pack(fill="x", padx=PAD_S, pady=PAD_S // 2 + 1)
            head = ctk.CTkFrame(box, fg_color="transparent")
            head.pack(fill="x", padx=PAD_M, pady=(PAD_M, 0))
            label(head, fmt.stars(review.rating), size=14,
                  color=COLORS["warning"]).pack(side="left")
            label(head, review.user_name, size=13, weight="bold").pack(side="left", padx=PAD_M)
            muted(head, fmt.day(review.created_at), size=12).pack(side="right")
            comment = label(box, review.comment or "(No comment)", size=13,
                            color=COLORS["text"] if review.comment else COLORS["text_muted"],
                            wraplength=600)
            comment.pack(fill="x", padx=PAD_M, pady=(PAD_S, PAD_M))
            auto_wrap(comment, box, padding=2 * PAD_M)

    # ------------------------------------------------------------------ actions

    def _open_other(self, product_id: int) -> None:
        # Stay on this screen and keep the same Back target.
        self.on_show(product_id=product_id)

    def _add_to_cart(self, product: ProductDetail, qty: int, button: ctk.CTkButton) -> None:
        button.configure(state="disabled")

        def added(_cart) -> None:
            button.configure(state="normal")
            self.app.show_message("Added to cart",
                                  f"{qty} × {product.name} added to your cart.",
                                  kind="success")

        def failed(error) -> None:
            button.configure(state="normal")
            self.app.show_error(error)

        self.app.tasks.run(cart_service.add_to_cart, self.app.user, product.id, qty,
                           on_success=added, on_error=failed, message="Adding to cart...")
