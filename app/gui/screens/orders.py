"""My Orders: order list on the left, selected order's details and status timeline on
the right. Delivered items get a "RATE & REVIEW" button."""

from dataclasses import dataclass

import customtkinter as ctk

from app.gui import formatting as fmt
from app.gui import theme
from app.gui.screens.base import Screen
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S, PAD_XL, PAD_XS
from app.gui.widgets.common import (
    caps_heading, card, clear, divider, icon, label, make_clickable, muted,
)
from app.gui.widgets import order_parts
from app.gui.widgets.review_dialog import ReviewDialog
from app.services import order_service, review_service
from app.services.dto import OrderDetail, OrderSummary


@dataclass
class OrderPage:
    detail: OrderDetail
    reviewable: set[int]  # product ids the user can review now


def load_order(user, order_id: int) -> OrderPage:
    """Background thread: the order and which of its items can be reviewed."""
    return OrderPage(order_service.get_order_detail(user, order_id),
                     review_service.reviewable_products(user, order_id))


class OrdersScreen(Screen):
    title = "My Orders"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=2, uniform="orders")
        self.grid_columnconfigure(1, weight=3, uniform="orders")
        self.grid_rowconfigure(0, weight=1)

        # Left: one white panel listing the orders, newest first.
        list_panel = card(self)
        list_panel.grid(row=0, column=0, sticky="nsew", padx=(PAD_M, PAD_S), pady=PAD_M)
        self._list = ctk.CTkScrollableFrame(list_panel, fg_color="transparent")
        self._list.pack(fill="both", expand=True, padx=1, pady=1)
        # Right: the selected order (its own white panels, on the grey background).
        self._detail = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._detail.grid(row=0, column=1, sticky="nsew", padx=(PAD_S, PAD_S), pady=(PAD_M - 2, PAD_M))

        self._selected: int | None = None
        self._rows: dict[int, ctk.CTkFrame] = {}
        self._dialog: ReviewDialog | None = None

    def on_show(self, order_id: int | None = None, **kwargs) -> None:
        if order_id is not None:
            self._selected = order_id  # e.g. just placed this order
        self.app.tasks.run(order_service.list_orders, self.app.user,
                           on_success=self._render_list, message="Loading your orders...")

    # ------------------------------------------------------------------ list

    def _render_list(self, orders: list[OrderSummary]) -> None:
        clear(self._list)
        self._rows.clear()
        if not orders:
            clear(self._detail)
            box = ctk.CTkFrame(self._list, fg_color="transparent")
            box.pack(pady=PAD_XL * 2)
            icon(box, theme.ICONS["orders"], size=56, color=COLORS["accent"]).pack()
            label(box, "You have no orders yet", size=16, weight="bold").pack(pady=(PAD_M, 2))
            muted(box, "Orders you place will appear here.", size=13).pack()
            ctk.CTkButton(box, text="SHOP NOW", width=200,
                          command=lambda: self.app.navigate("shop"),
                          **theme.buy_button_style()).pack(pady=(PAD_L, 0))
            return
        for index, order in enumerate(orders):
            if index:
                divider(self._list).pack(fill="x")
            self._rows[order.id] = self._order_row(order)
        if self._selected not in self._rows:
            self._selected = orders[0].id  # newest first
        self._select(self._selected)

    def _order_row(self, order: OrderSummary) -> ctk.CTkFrame:
        box = ctk.CTkFrame(self._list, fg_color=COLORS["surface"], corner_radius=0)
        box.pack(fill="x")
        box.grid_columnconfigure(1, weight=1)
        # 3 px blue bar on the left of the selected order (shown in _select).
        # (height=1: an empty CTkFrame would otherwise ask for its default 200 px.)
        box.marker = ctk.CTkFrame(box, width=3, height=1, fg_color="transparent",
                                  corner_radius=0)
        box.marker.grid(row=0, column=0, rowspan=2, sticky="ns")
        label(box, f"Order #{order.id}", size=14, weight="bold").grid(
            row=0, column=1, sticky="w", padx=PAD_M, pady=(PAD_M, 0))
        muted(box, f"{fmt.day(order.created_at)}  ·  {order.item_count} item"
                   f"{'s' if order.item_count != 1 else ''}", size=12).grid(
            row=1, column=1, sticky="w", padx=PAD_M, pady=(0, PAD_M))
        label(box, fmt.inr(order.total), size=14, weight="bold").grid(
            row=0, column=2, sticky="e", padx=PAD_M, pady=(PAD_M, 0))
        order_parts.status_text(box, order.status).grid(
            row=1, column=2, sticky="e", padx=PAD_M, pady=(0, PAD_M))
        make_clickable(box, lambda: self._select(order.id))
        return box

    def _select(self, order_id: int) -> None:
        self._selected = order_id
        for row_id, row in self._rows.items():
            chosen = row_id == order_id
            row.configure(fg_color=COLORS["selected_nav"] if chosen else COLORS["surface"])
            row.marker.configure(fg_color=COLORS["accent"] if chosen else "transparent")
        clear(self._detail)
        self.app.tasks.run(load_order, self.app.user, order_id,
                           on_success=lambda page: self._render_detail(order_id, page),
                           message="Loading order...")

    # ------------------------------------------------------------------ detail

    def _render_detail(self, order_id: int, page: OrderPage) -> None:
        if order_id != self._selected:
            return
        clear(self._detail)
        order = page.detail

        head = card(self._detail)
        head.pack(fill="x", padx=PAD_XS, pady=(0, PAD_S))
        head.grid_columnconfigure(0, weight=1)
        label(head, f"Order #{order.id}", size=18, weight="bold").grid(
            row=0, column=0, sticky="w", padx=PAD_L, pady=(PAD_M, 0))
        muted(head, f"Placed {fmt.when(order.created_at)}", size=12).grid(
            row=1, column=0, sticky="w", padx=PAD_L, pady=(0, PAD_M))
        order_parts.status_text(head, order.status, size=14).grid(
            row=0, column=1, rowspan=2, padx=PAD_L)

        order_parts.timeline(self._detail, order)
        self._render_items(order, page.reviewable)
        order_parts.totals(self._detail, order)

    def _render_items(self, order: OrderDetail, reviewable: set[int]) -> None:
        box = card(self._detail)
        box.pack(fill="x", padx=PAD_XS, pady=(0, PAD_S))
        caps_heading(box, f"Items ({len(order.lines)})").pack(
            fill="x", padx=PAD_L, pady=(PAD_M, PAD_XS))
        for index, line in enumerate(order.lines):
            if index:
                divider(box).pack(fill="x", padx=PAD_L)
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", padx=PAD_L, pady=PAD_S)
            row.grid_columnconfigure(0, weight=1)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.grid(row=0, column=0, sticky="w")
            name = label(info, line.name, size=14, wraplength=300)
            name.pack(fill="x")
            name.bind("<Button-1>", lambda _e, pid=line.product_id: self.app.navigate(
                "product", product_id=pid, back_to="orders"))
            name.configure(cursor="hand2")
            muted(info, f"{line.qty} × {fmt.inr(line.unit_price)}", size=12).pack(fill="x")
            label(row, fmt.inr(line.line_total), size=14, weight="bold").grid(
                row=0, column=1, padx=PAD_M)
            if line.product_id in reviewable:
                ctk.CTkButton(row, text="RATE & REVIEW", width=124,
                              command=lambda l=line: self._open_review(order.id, l),
                              **theme.secondary_button_style()).grid(row=0, column=2)
        ctk.CTkFrame(box, height=PAD_XS, width=1, fg_color="transparent").pack()

    # ------------------------------------------------------------------ reviews

    def _open_review(self, order_id: int, line) -> None:
        if self._dialog is not None and self._dialog.winfo_exists():
            self._dialog.focus_set()
            return
        self._dialog = ReviewDialog(
            self, line.name,
            on_submit=lambda rating, comment: self._submit_review(order_id, line, rating, comment))

    def _submit_review(self, order_id: int, line, rating: int, comment: str) -> None:
        def saved(_review) -> None:
            if self._dialog is not None:
                self._dialog.destroy()
            self.app.show_message("Thank you!", "Your review has been posted.", kind="success")
            self._select(order_id)  # redraw: the button disappears for this item

        def failed(error) -> None:
            if self._dialog is not None:
                self._dialog.submission_failed()
            self.app.show_error(error)

        self.app.tasks.run(review_service.add_review, self.app.user, line.product_id,
                           rating, comment, on_success=saved, on_error=failed,
                           message="Posting review...")
