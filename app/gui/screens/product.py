"""Product page, two columns like Flipkart:

    < Back to Shop  ›  Footwear
    +-----------------------+------------------------------------------+
    |  [ category tile ]    | Name                                     |
    |                       | 4.3 ★ (12)  ·  Customers love it         |
    |  Quantity  - 1 +      | ₹2,499.00                                |
    | [ADD TO CART][BUY NOW]| In stock                                 |
    |                       | DESCRIPTION ...                          |
    |                       | Frequently bought together  [tiles]      |
    |                       | Similar products            [tiles]      |
    |                       | Ratings & Reviews ...                    |
    +-----------------------+------------------------------------------+
"""

from dataclasses import dataclass

import customtkinter as ctk

from app.gui import formatting as fmt
from app.gui import theme
from app.gui.screens.base import Screen
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S, PAD_XS
from app.gui.widgets.common import (
    QuantityStepper, auto_wrap, caps_heading, card, category_tile, clear, divider,
    empty_state, label, link_button, muted, pill, rating_pill, section_title,
)
from app.gui.widgets.product_card import ProductCard
from app.services import cart_service, catalog_service, review_service
from app.services.dto import ProductDetail, ProductSentiment, ProductSummary, ReviewInfo

RECOMMENDATIONS = 5
LEFT_WIDTH = 340   # the picture-and-buttons column
BACK_LABELS = {"shop": "Shop", "cart": "Cart", "orders": "Orders"}


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
    show_title = False  # the breadcrumb and product name are the heading

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self._back_to = "shop"
        self._product_id: int | None = None
        self._request = 0

        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.pack(fill="both", expand=True, padx=PAD_S, pady=(0, PAD_S))

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
        p = page.product

        # Breadcrumb: "< Back to Shop  ›  Footwear"
        crumbs = ctk.CTkFrame(self._body, fg_color="transparent")
        crumbs.pack(fill="x", padx=PAD_XS, pady=(0, PAD_XS))
        link_button(crumbs, f"‹ Back to {BACK_LABELS.get(self._back_to, 'Shop')}",
                    lambda: self.app.navigate(self._back_to)).pack(side="left")
        muted(crumbs, f"›   {p.category}", size=12).pack(side="left", padx=PAD_XS)

        # One white panel, two columns: picture + buttons | details.
        panel = card(self._body)
        panel.pack(fill="x", padx=PAD_XS)
        panel.grid_columnconfigure(1, weight=1)
        left = ctk.CTkFrame(panel, fg_color="transparent", width=LEFT_WIDTH)
        left.grid(row=0, column=0, sticky="n", padx=(PAD_L, PAD_M), pady=PAD_L)
        right = ctk.CTkFrame(panel, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(PAD_M, PAD_L), pady=PAD_L)

        self._render_buy_column(left, p)
        self._render_details(right, page)
        self._render_row(right, "Frequently bought together", page.bought_together,
                         "Not enough orders yet to show products bought with this one.")
        self._render_row(right, "Similar products", page.similar,
                         "No similar products found.")
        self._render_reviews(right, page)

    def _render_buy_column(self, parent, p: ProductDetail) -> None:
        tile = category_tile(parent, p.category, height=300, icon_size=110)
        tile.configure(width=LEFT_WIDTH)
        tile.pack(fill="x")

        can_buy = p.is_active and p.stock > 0
        qty_row = ctk.CTkFrame(parent, fg_color="transparent")
        qty_row.pack(fill="x", pady=(PAD_M, PAD_S))
        muted(qty_row, "Quantity", size=12).pack(side="left", padx=(0, PAD_M))
        stepper = QuantityStepper(qty_row, 1, on_change=lambda _v: None,
                                  maximum=max(1, min(p.stock, 10)))
        stepper.pack(side="left")
        stepper.set_enabled(can_buy)

        buttons = ctk.CTkFrame(parent, fg_color="transparent")
        buttons.pack(fill="x")
        buttons.grid_columnconfigure((0, 1), weight=1, uniform="buy")
        add = ctk.CTkButton(buttons, text=f"{theme.ICONS['cart']}  ADD TO CART",
                            **theme.cart_button_style())
        buy = ctk.CTkButton(buttons, text="BUY NOW", **theme.buy_button_style())
        add.configure(command=lambda: self._add_to_cart(p, stepper.value, add))
        buy.configure(command=lambda: self._add_to_cart(p, stepper.value, buy,
                                                        then_open_cart=True))
        add.grid(row=0, column=0, sticky="ew", padx=(0, PAD_XS))
        buy.grid(row=0, column=1, sticky="ew", padx=(PAD_XS, 0))
        if not can_buy:
            reason = "UNAVAILABLE" if not p.is_active else "OUT OF STOCK"
            for button in (add, buy):
                button.configure(state="disabled", fg_color=COLORS["disabled"])
            add.configure(text=reason)

    def _render_details(self, parent, page: ProductPage) -> None:
        p = page.product
        name = label(parent, p.name, size=19, wraplength=500)
        name.pack(fill="x")
        auto_wrap(name, parent)

        rating = ctk.CTkFrame(parent, fg_color="transparent")
        rating.pack(fill="x", pady=(PAD_S, 0))
        rating_pill(rating, p.avg_rating, p.review_count).pack(side="left")
        if page.sentiment.badge:
            label(rating, f"·   {fmt.sentiment_text(page.sentiment.badge)}", size=13,
                  weight="bold", color=fmt.BADGE_COLORS[page.sentiment.badge]).pack(
                side="left", padx=PAD_M)

        label(parent, fmt.inr(p.price), size=26, weight="bold").pack(
            fill="x", pady=(PAD_M, 0))
        text, color = fmt.stock_text(p.stock, p.is_active)
        label(parent, text, size=13, weight="bold", color=color).pack(fill="x")

        divider(parent).pack(fill="x", pady=PAD_M)
        caps_heading(parent, "Description").pack(fill="x")
        description = label(parent, p.description, size=13, wraplength=500)
        description.pack(fill="x", pady=(PAD_XS, 0))
        auto_wrap(description, parent)

    def _render_row(self, parent, title: str, products: list[ProductSummary],
                    empty: str) -> None:
        divider(parent).pack(fill="x", pady=PAD_M)
        section_title(parent, title).pack(fill="x", pady=(0, PAD_S))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        if not products:
            empty_state(row, empty).pack(anchor="w")
            return
        for column in range(RECOMMENDATIONS):
            row.grid_columnconfigure(column, weight=1, uniform="rec")
        for index, product in enumerate(products):
            ProductCard(row, product, compact=True, on_open=self._open_other).grid(
                row=0, column=index, sticky="nsew", padx=(0 if index == 0 else PAD_XS, 0))

    def _render_reviews(self, parent, page: ProductPage) -> None:
        divider(parent).pack(fill="x", pady=PAD_M)
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.pack(fill="x")
        section_title(head, "Ratings & Reviews").pack(side="left")
        muted(head, f"{len(page.reviews)} review{'' if len(page.reviews) == 1 else 's'}",
              size=12).pack(side="left", padx=PAD_M)
        if not page.reviews:
            empty_state(parent, "No reviews yet. Customers can review a product "
                                "after it is delivered.").pack(fill="x", pady=(PAD_S, 0))
            return
        for index, review in enumerate(page.reviews):
            if index:
                divider(parent).pack(fill="x")
            box = ctk.CTkFrame(parent, fg_color="transparent")
            box.pack(fill="x", pady=PAD_M)
            # Flipkart colours a review's own rating: green 3-5, orange 2, red 1.
            color = (COLORS["success"] if review.rating >= 3 else
                     COLORS["warning"] if review.rating == 2 else COLORS["danger"])
            top = ctk.CTkFrame(box, fg_color="transparent")
            top.pack(fill="x")
            pill(top, f"{review.rating} ★", color).pack(side="left")
            comment = label(box, review.comment or "(No comment)", size=13,
                            color=COLORS["text"] if review.comment else COLORS["text_muted"],
                            wraplength=600)
            comment.pack(fill="x", pady=(PAD_XS, 2))
            auto_wrap(comment, box)
            muted(box, f"{review.user_name}  ·  {fmt.day(review.created_at)}", size=12).pack(
                fill="x")

    # ------------------------------------------------------------------ actions

    def _open_other(self, product_id: int) -> None:
        # Stay on this screen and keep the same Back target.
        self.on_show(product_id=product_id)

    def _add_to_cart(self, product: ProductDetail, qty: int, button: ctk.CTkButton,
                     then_open_cart: bool = False) -> None:
        """ADD TO CART, or BUY NOW (then_open_cart=True): the same service call; BUY NOW
        then goes straight to the cart to check out."""
        button.configure(state="disabled")

        def added(_cart) -> None:
            button.configure(state="normal")
            if then_open_cart:
                self.app.navigate("cart")
            else:
                self.app.show_message("Added to cart",
                                      f"{qty} × {product.name} added to your cart.",
                                      kind="success")

        def failed(error) -> None:
            button.configure(state="normal")
            self.app.show_error(error)

        self.app.tasks.run(cart_service.add_to_cart, self.app.user, product.id, qty,
                           on_success=added, on_error=failed, message="Adding to cart...")
