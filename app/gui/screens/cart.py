"""Cart: quantities, remove, coupon, totals, payment method, checkout.

Every change is sent to cart_service, which returns the updated CartView; the screen
then simply redraws from it. Totals are never calculated in the GUI.
"""

import customtkinter as ctk

from app.gui import formatting as fmt
from app.gui import theme
from app.gui.screens.base import Screen
from app.gui.theme import COLORS, CORNER_RADIUS, PAD_L, PAD_M, PAD_S, PAD_XL
from app.gui.widgets.common import (
    QuantityStepper, auto_wrap, card, clear, empty_state, form_entry, label, link_button, muted,
    section_title,
)
from app.exceptions import InvalidCouponError
from app.services import cart_service, order_service
from app.services.dto import CartLine, CartView

# Button label -> payment method code expected by order_service.checkout.
PAYMENT_METHODS = {"UPI": "upi", "Card": "card", "COD": "cod", "Wallet": "wallet"}


def line_problem(line: CartLine) -> str | None:
    """A clear message if this line can't be checked out as it is."""
    if not line.is_active:
        return "No longer available. Please remove it."
    if line.stock <= 0:
        return "Out of stock. Please remove it."
    if line.qty > line.stock:
        return f"Only {line.stock} left. Please lower the quantity."
    return None


class CartScreen(Screen):
    title = "Cart"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._lines = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._lines.grid(row=0, column=0, sticky="nsew", padx=(PAD_L, PAD_S), pady=(0, PAD_L))

        self._summary = card(self, width=340)
        self._summary.grid(row=0, column=1, sticky="n", padx=(PAD_S, PAD_XL), pady=(PAD_S, PAD_L))
        self._build_summary()
        self._cart: CartView | None = None

    def _build_summary(self) -> None:
        s = self._summary
        section_title(s, "Order summary").pack(fill="x", padx=PAD_L, pady=(PAD_L, PAD_M))
        self._subtotal = self._summary_row("Subtotal")
        self._discount = self._summary_row("Discount")
        ctk.CTkFrame(s, height=1, fg_color=COLORS["border"]).pack(fill="x", padx=PAD_L, pady=PAD_S)
        self._total = self._summary_row("Total", bold=True)

        label(s, "Coupon", size=13, weight="bold").pack(fill="x", padx=PAD_L, pady=(PAD_M, 4))
        coupon_row = ctk.CTkFrame(s, fg_color="transparent")
        coupon_row.pack(fill="x", padx=PAD_L)
        self._coupon = form_entry(coupon_row, "e.g. WELCOME10")
        self._coupon.configure(width=170)
        self._coupon.pack(side="left")
        self._coupon.bind("<Return>", lambda _e: self._apply_coupon())
        ctk.CTkButton(coupon_row, text="Apply", width=80, command=self._apply_coupon,
                      **theme.secondary_button_style()).pack(side="left", padx=(PAD_S, 0))
        self._coupon_info = muted(s, "", size=12)
        self._coupon_info.pack(fill="x", padx=PAD_L, pady=(4, 0))
        self._remove_coupon = link_button(s, "Remove coupon", self._clear_coupon)

        label(s, "Payment method", size=13, weight="bold").pack(
            fill="x", padx=PAD_L, pady=(PAD_M, 4))
        self._payment = ctk.CTkSegmentedButton(
            s, values=list(PAYMENT_METHODS),
            font=theme.font(13), selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"], unselected_color=COLORS["bg"],
            unselected_hover_color=COLORS["surface_hover"], text_color=COLORS["text"])
        self._payment.set("UPI")
        self._payment.pack(fill="x", padx=PAD_L)
        muted(s, "Payments are simulated; no card details are collected.", size=11,
              wraplength=290).pack(fill="x", padx=PAD_L, pady=(4, 0))

        self._checkout = ctk.CTkButton(s, text="Place order", command=self._place_order,
                                       **theme.primary_button_style())
        self._checkout.pack(fill="x", padx=PAD_L, pady=(PAD_M, PAD_S))
        self._problem = label(s, "", size=12, color=COLORS["danger"], wraplength=290)
        self._problem.pack(fill="x", padx=PAD_L, pady=(0, PAD_L))

    def _summary_row(self, name: str, bold: bool = False) -> ctk.CTkLabel:
        row = ctk.CTkFrame(self._summary, fg_color="transparent")
        row.pack(fill="x", padx=PAD_L, pady=2)
        weight = "bold" if bold else "normal"
        label(row, name, size=15 if bold else 14, weight=weight).pack(side="left")
        value = label(row, "", size=15 if bold else 14, weight=weight)
        value.pack(side="right")
        return value

    # ------------------------------------------------------------------ loading

    def on_show(self, **kwargs) -> None:
        self._run(cart_service.get_cart, self.app.user, self.app.cart_coupon,
                  message="Loading cart...")

    def _run(self, func, *args, message: str) -> None:
        self.app.tasks.run(func, *args, on_success=self._after_change, message=message,
                           on_error=self._failed)

    def _after_change(self, cart: CartView) -> None:
        # update_quantity / remove_from_cart don't know about the coupon (the GUI keeps
        # it), so their totals have no discount. If a coupon is applied, fetch the cart
        # again WITH the coupon; this runs after the change, never at the same time.
        if self.app.cart_coupon and cart.coupon is None and not cart.is_empty:
            self.app.tasks.run(cart_service.get_cart, self.app.user, self.app.cart_coupon,
                               on_success=self._render, on_error=self._failed,
                               message="Updating totals...")
        else:
            self._render(cart)

    def _failed(self, error) -> None:
        self.app.show_error(error)
        if self.app.cart_coupon and isinstance(error, InvalidCouponError):
            self._clear_coupon()  # e.g. the coupon expired while in the cart

    # ------------------------------------------------------------------ rendering

    def _render(self, cart: CartView) -> None:
        self._cart = cart
        clear(self._lines)
        if cart.is_empty:
            box = card(self._lines)
            box.pack(fill="x", padx=PAD_S, pady=PAD_S)
            label(box, "Your cart is empty", size=18, weight="bold").pack(
                fill="x", padx=PAD_L, pady=(PAD_L, 2))
            empty_state(box, "Browse the shop and add something you like.").pack(
                fill="x", padx=PAD_L)
            ctk.CTkButton(box, text="Go to shop", width=140,
                          command=lambda: self.app.navigate("shop"),
                          **theme.primary_button_style()).pack(anchor="w", padx=PAD_L, pady=PAD_L)
        for line in cart.lines:
            self._render_line(line)

        self._subtotal.configure(text=fmt.inr(cart.subtotal))
        self._discount.configure(text=f"− {fmt.inr(cart.discount)}" if cart.discount else "-")
        self._total.configure(text=fmt.inr(cart.total))
        if cart.coupon:
            self._coupon_info.configure(text=f"{cart.coupon.code} applied: "
                                             f"{cart.coupon.percent_off}% off",
                                        text_color=COLORS["success"])
            self._remove_coupon.pack(anchor="w", padx=PAD_L - 6, after=self._coupon_info)
        else:
            self._coupon_info.configure(text="")
            self._remove_coupon.pack_forget()

        problems = [line for line in cart.lines if line_problem(line)]
        if cart.is_empty:
            self._problem.configure(text="")
            self._checkout.configure(state="disabled")
        elif problems:
            self._problem.configure(text="Some items can't be ordered as they are. "
                                         "Please fix the items marked in red.")
            self._checkout.configure(state="disabled")
        else:
            self._problem.configure(text="")
            self._checkout.configure(state="normal")

    def _render_line(self, line: CartLine) -> None:
        problem = line_problem(line)
        box = card(self._lines, border_width=1 if problem else 0,
                   border_color=COLORS["danger"])
        box.pack(fill="x", padx=PAD_S, pady=PAD_S // 2 + 1)
        box.grid_columnconfigure(0, weight=1)

        # Text block on the left takes all spare width; its labels wrap to that width.
        text = ctk.CTkFrame(box, fg_color="transparent")
        text.grid(row=0, column=0, sticky="ew", padx=PAD_M, pady=PAD_M)
        name = label(text, line.name, size=14, weight="bold", wraplength=200)
        name.pack(fill="x")
        auto_wrap(name, text)
        name.bind("<Button-1>", lambda _e: self.app.navigate(
            "product", product_id=line.product_id, back_to="cart"))
        name.configure(cursor="hand2")
        muted(text, f"{fmt.inr(line.unit_price)} each", size=12).pack(fill="x")
        if problem:
            message = label(text, problem, size=12, color=COLORS["danger"], wraplength=200)
            message.pack(fill="x", pady=(2, 0))
            auto_wrap(message, text)

        stepper = QuantityStepper(box, line.qty, maximum=max(line.qty, min(line.stock, 99)),
                                  on_change=lambda qty: self._set_qty(line, qty))
        stepper.grid(row=0, column=1, padx=PAD_M)
        stepper.set_enabled(line.is_active)
        label(box, fmt.inr(line.line_total), size=15, weight="bold", width=110).grid(
            row=0, column=2, padx=PAD_M)
        ctk.CTkButton(box, text="Remove", width=80, height=32, corner_radius=CORNER_RADIUS,
                      fg_color="transparent", hover_color=COLORS["surface_hover"],
                      text_color=COLORS["danger"], font=theme.font(13),
                      command=lambda: self._remove(line)).grid(
            row=0, column=3, padx=(0, PAD_M))

    # ------------------------------------------------------------------ actions

    def _set_qty(self, line: CartLine, qty: int) -> None:
        self._run(cart_service.update_quantity, self.app.user, line.product_id, qty,
                  message="Updating cart...")

    def _remove(self, line: CartLine) -> None:
        self._run(cart_service.remove_from_cart, self.app.user, line.product_id,
                  message="Removing item...")

    def _apply_coupon(self) -> None:
        code = self._coupon.get().strip()
        if not code:
            return

        def applied(cart: CartView) -> None:
            self.app.cart_coupon = cart.coupon.code
            self._coupon.delete(0, "end")
            self._render(cart)

        self.app.tasks.run(cart_service.apply_coupon, self.app.user, code,
                           on_success=applied, message="Checking coupon...")

    def _clear_coupon(self) -> None:
        self.app.cart_coupon = None
        self.on_show()

    def _place_order(self) -> None:
        method = PAYMENT_METHODS[self._payment.get()]
        self._checkout.configure(state="disabled")  # no double orders

        def placed(order) -> None:
            self.app.cart_coupon = None
            self.app.show_message("Order placed",
                                  f"Thank you! Order #{order.id} for {fmt.inr(order.total)} "
                                  "has been placed.", kind="success")
            self.app.navigate("orders", order_id=order.id)

        def failed(error) -> None:
            self.app.show_error(error)
            self.on_show()  # stock may have changed: redraw with the latest numbers

        self.app.tasks.run(order_service.checkout, self.app.user, method, self.app.cart_coupon,
                           on_success=placed, on_error=failed, message="Placing your order...")
