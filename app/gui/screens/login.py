"""Login screen, in Flipkart's two-panel style (also used by the register screen):

    +-------------------+---------------------------------+
    | Login             |  Email                          |
    |                   |  [..........................]   |
    | Get access to     |  Password                       |
    | your orders, ...  |  [..........................]   |
    |                   |  [          LOGIN          ]    |
    |      (icon)       |                                 |
    |                   |  New to ShopSense? Create an account
    +-------------------+---------------------------------+
"""

import customtkinter as ctk

from app.gui import theme
from app.gui.screens.base import Screen
from app.gui.theme import COLORS, CORNER_RADIUS, ICONS, PAD_L, PAD_M, PAD_S, PAD_XL
from app.gui.widgets.common import card, field_label, form_entry, link_button, muted
from app.services import auth_service

PANEL_SIZE = (720, 470)


def two_panel(screen: Screen, heading: str, blurb: str) -> ctk.CTkFrame:
    """Build the centred card: blue panel with `heading` and `blurb` on the left, and
    return the white right-hand panel for the form."""
    box = card(screen, width=PANEL_SIZE[0], height=PANEL_SIZE[1])
    box.place(relx=0.5, rely=0.45, anchor="center")
    box.grid_propagate(False)
    box.grid_columnconfigure(0, minsize=270)
    box.grid_columnconfigure(1, weight=1)
    box.grid_rowconfigure(0, weight=1)

    left = ctk.CTkFrame(box, fg_color=COLORS["header"], corner_radius=CORNER_RADIUS)
    left.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=1)
    ctk.CTkLabel(left, text=heading, font=theme.font(24, "bold"), wraplength=210,
                 text_color=COLORS["header_text"], anchor="w", justify="left").pack(
        fill="x", padx=PAD_XL + 4, pady=(PAD_XL + 8, PAD_M))
    ctk.CTkLabel(left, text=blurb, font=theme.font(15), wraplength=210,
                 text_color=COLORS["header_muted"], anchor="w", justify="left").pack(
        fill="x", padx=PAD_XL + 4)
    ctk.CTkLabel(left, text=ICONS["cart"], font=theme.icon_font(84),
                 text_color=COLORS["header_muted"]).pack(side="bottom", pady=PAD_XL + 8)

    right = ctk.CTkFrame(box, fg_color="transparent")
    right.grid(row=0, column=1, sticky="nsew", padx=PAD_XL, pady=(PAD_XL, PAD_L))
    return right


class LoginScreen(Screen):
    title = "Sign in"
    show_title = False  # the card has its own heading

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        form = two_panel(self, "Login", "Get access to your orders, your cart and "
                                        "recommendations picked for you.")

        # Labels above the fields: CustomTkinter doesn't show placeholder text in a
        # password field (show="•"), so placeholders alone would leave it unlabelled.
        field_label(form, "Email address").pack(fill="x", pady=(PAD_M, 0))
        self._email = form_entry(form, "you@example.com")
        self._email.pack(fill="x", pady=(2, PAD_M))
        field_label(form, "Password").pack(fill="x")
        self._password = form_entry(form, "", show="•")
        self._password.pack(fill="x", pady=(2, PAD_S))
        muted(form, "Accounts lock for 15 minutes after 5 wrong passwords.", size=11).pack(
            fill="x", pady=(0, PAD_L))

        self._button = ctk.CTkButton(form, text="LOGIN", command=self._submit,
                                     **theme.buy_button_style())
        self._button.pack(fill="x")

        footer = ctk.CTkFrame(form, fg_color="transparent")
        footer.pack(side="bottom", fill="x")
        muted(footer, "New to ShopSense?").pack(side="left")
        link_button(footer, "Create an account",
                    lambda: self.app.navigate("register")).pack(side="left", padx=(2, 0))

        for entry in (self._email, self._password):
            entry.bind("<Return>", lambda _e: self._submit())

    def on_show(self, email: str = "", **kwargs) -> None:
        self._password.delete(0, "end")
        if email:  # coming from registration, or after logout
            self._email.delete(0, "end")
            self._email.insert(0, email)
        (self._password if self._email.get() else self._email).focus_set()

    def _submit(self) -> None:
        email, password = self._email.get().strip(), self._password.get()
        if not email or not password:
            self.app.show_message("Missing details", "Please enter your email and password.")
            return
        self._button.configure(state="disabled")  # no double submits while waiting
        self.app.tasks.run(auth_service.login, email, password,
                           on_success=self._logged_in, on_error=self._failed,
                           message="Signing in...")

    def _logged_in(self, user) -> None:
        self._button.configure(state="normal")
        self._password.delete(0, "end")
        self.app.login(user)

    def _failed(self, error) -> None:
        self._button.configure(state="normal")
        self._password.delete(0, "end")
        self.app.show_error(error)
