"""Pieces of an order's detail view shared by the customer's "My Orders" screen and the
admin Orders screen: the status text, the status timeline and the price details."""

import customtkinter as ctk

from app.gui import formatting as fmt
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S, PAD_XS
from app.gui.widgets.common import caps_heading, card, divider, label, muted
from app.services.dto import OrderDetail


def status_color(status: str) -> str:
    """Flipkart marks progress in green; only a cancelled order is red."""
    return COLORS["danger"] if status == "cancelled" else COLORS["success"]


def status_text(parent, status: str, size: int = 12) -> ctk.CTkLabel:
    """"● Delivered" in the status colour."""
    return label(parent, f"● {status.capitalize()}", size=size, weight="bold",
                 color=status_color(status))


def timeline(parent, order: OrderDetail) -> None:
    """A panel with one dot per status change (from the order_status_history rows the
    trg_order_status trigger writes), joined by a vertical line."""
    box = card(parent)
    box.pack(fill="x", padx=PAD_XS, pady=(0, PAD_S))
    caps_heading(box, "Status timeline").pack(fill="x", padx=PAD_L, pady=(PAD_M, PAD_S))
    for index, change in enumerate(order.timeline):
        last = index == len(order.timeline) - 1
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=PAD_L, pady=(0, PAD_M if last else 0))
        dot_column = ctk.CTkFrame(row, fg_color="transparent", width=16)
        dot_column.pack(side="left", fill="y")
        color = status_color(change.new_status)
        ctk.CTkFrame(dot_column, width=12, height=12, corner_radius=6,
                     fg_color=color).pack(pady=(4, 0))
        if not last:  # vertical line connecting to the next step
            ctk.CTkFrame(dot_column, width=2, height=24, fg_color=color,
                         corner_radius=0).pack()
        text = ctk.CTkFrame(row, fg_color="transparent")
        text.pack(side="left", fill="x", padx=PAD_M)
        label(text, change.new_status.capitalize(), size=13, weight="bold").pack(fill="x")
        muted(text, fmt.when(change.changed_at), size=11).pack(fill="x")


def totals(parent, order: OrderDetail) -> None:
    """PRICE DETAILS: subtotal, discount, total and payment, one row each."""
    box = card(parent)
    box.pack(fill="x", padx=PAD_XS, pady=(0, PAD_S))
    caps_heading(box, "Price details").pack(fill="x", padx=PAD_L, pady=(PAD_M, PAD_S))
    divider(box).pack(fill="x")
    rows = [("Subtotal", fmt.inr(order.subtotal), None)]
    if order.discount:
        rows.append((f"Discount ({order.coupon_code})", f"− {fmt.inr(order.discount)}",
                     COLORS["success"]))
    rows.append(("Total", fmt.inr(order.total), None))
    if order.payment:
        rows.append(("Payment", f"{fmt.PAYMENT_METHOD_LABELS[order.payment.method]} "
                                f"· {order.payment.status}", None))
    for index, (name, value, color) in enumerate(rows):
        line = ctk.CTkFrame(box, fg_color="transparent")
        first, last = index == 0, index == len(rows) - 1
        line.pack(fill="x", padx=PAD_L, pady=(PAD_M if first else 2, PAD_M if last else 2))
        bold = "bold" if name == "Total" else "normal"
        label(line, name, size=14, weight=bold).pack(side="left")
        label(line, value, size=14, weight=bold, color=color).pack(side="right")
