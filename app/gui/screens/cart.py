"""Cart, Flipkart style: the items on the left with PLACE ORDER at the bottom, and the
PRICE DETAILS box (then coupon and payment method) on the right.

Every change is sent to cart_service, which returns the updated CartView; the screen
then simply redraws from it. Totals are never calculated in the GUI.
"""

import customtkinter as ctk

from app.gui import formatting as fmt
from app.gui import theme
from app.gui.screens.base import Screen
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S, PAD_XL, PAD_XS
from app.gui.widgets.common import (
    QuantityStepper, auto_wrap, caps_heading, card, category_tile, clear, divider, form_entry,
    icon, label, link_button, muted,
)
from app.exceptions import InvalidCouponError
from app.services import cart_service, order_service
from app.services.dto import CartLine, CartView

# Button label -> payment method code expected by order_service.checkout.
PAYMENT_METHODS = {"UPI": "upi", "Card": "card", "COD": "cod", "Wallet": "wallet"}
SIDE_WIDTH = 360  # the PRICE DETAILS column


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
    show_title = False  # "My Cart (N)" heads the items panel

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Left: the items panel, with the PLACE ORDER bar at its bottom.
        self._items = card(self)
        self._items.grid(row=0, column=0, sticky="nsew", padx=(PAD_M, PAD_S), pady=PAD_M)
        self._heading = label(self._items, "My Cart", size=17, weight="bold")
        self._heading.pack(fill="x", padx=PAD_L, pady=(PAD_M, PAD_S))
        divider(self._items).pack(fill="x")

        self._order_bar = ctk.CTkFrame(self._items, fg_color="transparent")
        self._order_bar.pack(side="bottom", fill="x")
        divider(self._order_bar).pack(fill="x")
        self._checkout = ctk.CTkButton(self._order_bar, text="PLACE ORDER", width=240,
                                       command=self._place_order, **theme.buy_button_style())
        self._checkout.pack(side="right", padx=PAD_L, pady=PAD_M)
        self._problem = label(self._order_bar, "", size=12, color=COLORS["danger"],
                              wraplength=380)
        self._problem.pack(side="left", padx=PAD_L)

        self._lines = ctk.CTkScrollableFrame(self._items, fg_color="transparent")
        self._lines.pack(fill="both", expand=True, padx=PAD_XS)

        # --- Right: PRICE DETAILS, then coupon and payment.
        self._side = ctk.CTkFrame(self, fg_color="transparent", width=SIDE_WIDTH)
        self._side.grid(row=0, column=1, sticky="n", padx=(PAD_S, PAD_M), pady=PAD_M)
        self._build_price_details()
        self._build_checkout_options()
        self._cart: CartView | None = None

    def _build_price_details(self) -> None:
        box = card(self._side, width=SIDE_WIDTH)
        box.pack(fill="x")
        caps_heading(box, "Price details").pack(fill="x", padx=PAD_L, pady=PAD_M)
        divider(box).pack(fill="x")
        rows = ctk.CTkFrame(box, fg_color="transparent")
        rows.pack(fill="x", padx=PAD_L, pady=(PAD_M, 0))
        self._price_label, self._subtotal = self._price_row(rows, "Price")
        _name, self._discount = self._price_row(rows, "Discount")
        self._discount.configure(text_color=COLORS["success"])
        divider(box).pack(fill="x", padx=PAD_L, pady=PAD_S)
        totals = ctk.CTkFrame(box, fg_color="transparent")
        totals.pack(fill="x", padx=PAD_L)
        _name, self._total = self._price_row(totals, "Total Amount", bold=True)
        ctk.CTkFrame(box, height=PAD_M, width=1, fg_color="transparent").pack()
        # "You will save ..." (packed only when there is a discount, see _render).
        self._savings_line = ctk.CTkFrame(box, fg_color="transparent")
        divider(self._savings_line).pack(fill="x", padx=PAD_L)
        self._savings = label(self._savings_line, "", size=13, weight="bold",
                              color=COLORS["success"])
        self._savings.pack(fill="x", padx=PAD_L, pady=PAD_M)

    def _price_row(self, parent, name: str, bold: bool = False):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        size, weight = (16, "bold") if bold else (14, "normal")
        name_label = label(row, name, size=size, weight=weight)
        name_label.pack(side="left")
        value = label(row, "", size=size, weight=weight)
        value.pack(side="right")
        return name_label, value

    def _build_checkout_options(self) -> None:
        box = card(self._side, width=SIDE_WIDTH)
        box.pack(fill="x", pady=(PAD_S, 0))
        caps_heading(box, "Apply coupon").pack(fill="x", padx=PAD_L, pady=(PAD_M, PAD_S))
        coupon_row = ctk.CTkFrame(box, fg_color="transparent")
        coupon_row.pack(fill="x", padx=PAD_L)
        coupon_row.grid_columnconfigure(0, weight=1)
        self._coupon = form_entry(coupon_row, "Enter coupon code, e.g. WELCOME10")
        self._coupon.configure(height=34)
        self._coupon.grid(row=0, column=0, sticky="ew")
        self._coupon.bind("<Return>", lambda _e: self._apply_coupon())
        ctk.CTkButton(coupon_row, text="APPLY", width=72, command=self._apply_coupon,
                      **theme.secondary_button_style()).grid(row=0, column=1, padx=(PAD_S, 0))
        self._coupon_info = muted(box, "", size=12)  # packed while a coupon is applied
        self._remove_coupon = link_button(box, "Remove coupon", self._clear_coupon)

        self._payment_heading = caps_heading(box, "Payment method")
        self._payment_heading.pack(fill="x", padx=PAD_L, pady=(PAD_M, PAD_S))
        self._payment = ctk.CTkSegmentedButton(
            box, values=list(PAYMENT_METHODS), font=theme.font(13), **theme.segmented_style())
        self._payment.set("UPI")
        self._payment.pack(fill="x", padx=PAD_L)
        muted(box, "Payments are simulated; no card details are collected.", size=11,
              wraplength=SIDE_WIDTH - 2 * PAD_L).pack(fill="x", padx=PAD_L, pady=(PAD_XS, PAD_M))

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
            self._render_empty()
        else:
            self._side.grid()
            # (A CTkScrollableFrame is packed through its outer frame, _parent_frame.)
            self._order_bar.pack(side="bottom", fill="x", before=self._lines._parent_frame)
            self._heading.configure(text=f"My Cart ({cart.item_count})")
            for index, line in enumerate(cart.lines):
                if index:
                    divider(self._lines).pack(fill="x", padx=PAD_M)
                self._render_line(line)

        count = cart.item_count
        self._price_label.configure(text=f"Price ({count} item{'' if count == 1 else 's'})")
        self._subtotal.configure(text=fmt.inr(cart.subtotal))
        self._discount.configure(text=f"− {fmt.inr(cart.discount)}" if cart.discount else "-")
        self._total.configure(text=fmt.inr(cart.total))
        if cart.discount:
            self._savings.configure(text=f"You will save {fmt.inr(cart.discount)} on this "
                                         "order")
            self._savings_line.pack(fill="x")
        else:
            self._savings_line.pack_forget()
        if cart.coupon:
            self._coupon_info.configure(text=f"{cart.coupon.code} applied: "
                                             f"{cart.coupon.percent_off}% off",
                                        text_color=COLORS["success"])
            self._coupon_info.pack(fill="x", padx=PAD_L, pady=(PAD_XS, 0),
                                   before=self._payment_heading)
            self._remove_coupon.pack(anchor="w", padx=PAD_L - 6, after=self._coupon_info)
        else:
            self._coupon_info.configure(text="")
            self._coupon_info.pack_forget()
            self._remove_coupon.pack_forget()

        problems = [line for line in cart.lines if line_problem(line)]
        if cart.is_empty:
            self._problem.configure(text="")
            self._checkout.configure(state="disabled")
        elif problems:
            self._problem.configure(text="Some items can't be ordered as they are. "
                                         "Please fix the items marked in red.")
            self._checkout.configure(state="disabled", fg_color=COLORS["disabled"])
        else:
            self._problem.configure(text="")
            self._checkout.configure(state="normal", fg_color=COLORS["buy"])

    def _render_empty(self) -> None:
        """Flipkart-style empty cart: icon, two lines and a SHOP NOW button."""
        self._side.grid_remove()
        self._order_bar.pack_forget()
        self._heading.configure(text="My Cart")
        box = ctk.CTkFrame(self._lines, fg_color="transparent")
        box.pack(pady=(PAD_XL * 3, PAD_XL))
        icon(box, theme.ICONS["cart"], size=72, color=COLORS["accent"]).pack()
        label(box, "Your cart is empty!", size=18, weight="bold").pack(pady=(PAD_M, 2))
        muted(box, "Add items to it now.", size=13).pack()
        ctk.CTkButton(box, text="SHOP NOW", width=220, command=lambda: self.app.navigate("shop"),
                      **theme.buy_button_style()).pack(pady=(PAD_L, 0))

    def _render_line(self, line: CartLine) -> None:
        problem = line_problem(line)
        row = ctk.CTkFrame(self._lines, fg_color="transparent")
        row.pack(fill="x", padx=PAD_S, pady=PAD_M)
        row.grid_columnconfigure(1, weight=1)

        # A neutral tile stands in for the product photo (cart lines carry no category).
        thumb = category_tile(row, "", height=88, icon_size=34)
        thumb.configure(width=88)
        thumb.grid(row=0, column=0, rowspan=2, sticky="n", padx=(PAD_S, PAD_L))

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.grid(row=0, column=1, sticky="ew")
        name = label(info, line.name, size=14, wraplength=300)
        name.pack(fill="x")
        auto_wrap(name, info)
        name.bind("<Button-1>", lambda _e: self.app.navigate(
            "product", product_id=line.product_id, back_to="cart"))
        name.configure(cursor="hand2")
        label(info, fmt.inr(line.line_total), size=17, weight="bold").pack(
            fill="x", pady=(PAD_XS, 0))
        if line.qty > 1:
            muted(info, f"{fmt.inr(line.unit_price)} each", size=12).pack(fill="x")
        if problem:
            message = label(info, problem, size=12, weight="bold", color=COLORS["danger"],
                            wraplength=300)
            message.pack(fill="x", pady=(2, 0))
            auto_wrap(message, info)

        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.grid(row=1, column=1, sticky="w", pady=(PAD_S, 0))
        stepper = QuantityStepper(actions, line.qty, maximum=max(line.qty, min(line.stock, 99)),
                                  on_change=lambda qty: self._set_qty(line, qty))
        stepper.pack(side="left")
        stepper.set_enabled(line.is_active)
        ctk.CTkButton(actions, text="REMOVE", width=0, height=28, corner_radius=theme.CORNER_RADIUS,
                      fg_color="transparent", hover_color=COLORS["surface_hover"],
                      text_color=COLORS["text"], font=theme.font(13, "bold"),
                      command=lambda: self._remove(line)).pack(side="left", padx=(PAD_L, 0))

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
