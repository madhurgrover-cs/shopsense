"""Pieces of an order's detail view shared by the customer's "My Orders" screen and the
admin Orders screen: the status timeline and the totals card."""

import customtkinter as ctk

from app.gui import formatting as fmt
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S
from app.gui.widgets.common import card, label, muted, section_title
from app.services.dto import OrderDetail


def timeline(parent, order: OrderDetail) -> None:
    """"Status timeline" title + a card with one dot per status change (from the
    order_status_history rows the trg_order_status trigger writes)."""
    section_title(parent, "Status timeline").pack(fill="x", padx=PAD_S, pady=(0, PAD_S))
    box = card(parent)
    box.pack(fill="x", padx=PAD_S, pady=(0, PAD_M))
    for index, change in enumerate(order.timeline):
        last = index == len(order.timeline) - 1
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=PAD_L, pady=(PAD_M if index == 0 else 0, PAD_M if last else 0))
        dot_column = ctk.CTkFrame(row, fg_color="transparent", width=20)
        dot_column.pack(side="left", fill="y")
        ctk.CTkFrame(dot_column, width=12, height=12, corner_radius=6,
                     fg_color=fmt.ORDER_STATUS_COLORS[change.new_status]).pack(pady=(4, 0))
        if not last:  # vertical line connecting to the next step
            ctk.CTkFrame(dot_column, width=2, height=26, fg_color=COLORS["border"]).pack()
        text = ctk.CTkFrame(row, fg_color="transparent")
        text.pack(side="left", fill="x", padx=PAD_M)
        label(text, change.new_status.capitalize(), size=14, weight="bold").pack(fill="x")
        muted(text, fmt.when(change.changed_at), size=12).pack(fill="x")


def totals(parent, order: OrderDetail) -> None:
    """Subtotal, discount, total and payment, one row each."""
    box = card(parent)
    box.pack(fill="x", padx=PAD_S, pady=(0, PAD_M))
    rows = [("Subtotal", fmt.inr(order.subtotal))]
    if order.discount:
        rows.append((f"Discount ({order.coupon_code})", f"− {fmt.inr(order.discount)}"))
    rows.append(("Total", fmt.inr(order.total)))
    if order.payment:
        rows.append(("Payment", f"{fmt.PAYMENT_METHOD_LABELS[order.payment.method]} "
                                f"· {order.payment.status}"))
    for index, (name, value) in enumerate(rows):
        line = ctk.CTkFrame(box, fg_color="transparent")
        first, last = index == 0, index == len(rows) - 1
        line.pack(fill="x", padx=PAD_L, pady=(PAD_M if first else 2, PAD_M if last else 2))
        bold = "bold" if name == "Total" else "normal"
        label(line, name, size=14, weight=bold).pack(side="left")
        label(line, value, size=14, weight=bold).pack(side="right")
