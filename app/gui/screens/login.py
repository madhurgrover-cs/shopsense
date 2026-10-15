"""Sign-in screen."""

import customtkinter as ctk

from app.gui import theme
from app.gui.screens.base import Screen
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S, PAD_XL
from app.gui.widgets.common import card, field_label, form_entry, label, link_button, muted
from app.services import auth_service


class LoginScreen(Screen):
    title = "Sign in"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        box = card(self, width=420)
        box.place(relx=0.5, rely=0.42, anchor="center")  # centred on the screen

        label(box, "Welcome back", size=22, weight="bold").pack(
            fill="x", padx=PAD_XL, pady=(PAD_XL, 2))
        muted(box, "Sign in to continue shopping.").pack(fill="x", padx=PAD_XL, pady=(0, PAD_L))

        # Labels above the fields: CustomTkinter doesn't show placeholder text in a
        # password field (show="•"), so placeholders alone would leave it unlabelled.
        field_label(box, "Email").pack(fill="x", padx=PAD_XL)
        self._email = form_entry(box, "you@example.com")
        self._email.pack(fill="x", padx=PAD_XL, pady=(2, PAD_M))
        field_label(box, "Password").pack(fill="x", padx=PAD_XL)
        self._password = form_entry(box, "", show="•")
        self._password.pack(fill="x", padx=PAD_XL, pady=(2, PAD_L))

        self._button = ctk.CTkButton(box, text="Sign in", command=self._submit, width=356,
                                     **theme.primary_button_style())
        self._button.pack(fill="x", padx=PAD_XL)

        footer = ctk.CTkFrame(box, fg_color="transparent")
        footer.pack(fill="x", padx=PAD_XL, pady=(PAD_M, PAD_XL))
        muted(footer, "New to ShopSense?").pack(side="left")
        link_button(footer, "Create an account",
                    lambda: self.app.navigate("register")).pack(side="left", padx=PAD_S)

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
