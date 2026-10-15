"""Create-account screen. New accounts are always customers."""

import customtkinter as ctk

from app.gui import theme
from app.gui.screens.base import Screen
from app.gui.theme import PAD_L, PAD_M, PAD_S, PAD_XL
from app.gui.widgets.common import card, field_label, form_entry, label, link_button, muted
from app.services import auth_service


class RegisterScreen(Screen):
    title = "Create account"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        box = card(self, width=420)
        box.place(relx=0.5, rely=0.42, anchor="center")

        label(box, "Create your account", size=22, weight="bold").pack(
            fill="x", padx=PAD_XL, pady=(PAD_XL, 2))
        muted(box, "It takes less than a minute.").pack(fill="x", padx=PAD_XL, pady=(0, PAD_L))

        self._name = form_entry(box, "e.g. Asha Rao")
        self._email = form_entry(box, "you@example.com")
        self._password = form_entry(box, "", show="•")
        self._confirm = form_entry(box, "", show="•")
        fields = [("Full name", self._name), ("Email", self._email),
                  ("Password (at least 8 characters)", self._password),
                  ("Confirm password", self._confirm)]
        for text, entry in fields:
            field_label(box, text).pack(fill="x", padx=PAD_XL)
            entry.pack(fill="x", padx=PAD_XL, pady=(2, PAD_S + 2))
            entry.bind("<Return>", lambda _e: self._submit())

        self._button = ctk.CTkButton(box, text="Create account", command=self._submit,
                                     width=356, **theme.primary_button_style())
        self._button.pack(fill="x", padx=PAD_XL, pady=(PAD_S, 0))

        footer = ctk.CTkFrame(box, fg_color="transparent")
        footer.pack(fill="x", padx=PAD_XL, pady=(PAD_M, PAD_XL))
        muted(footer, "Already have an account?").pack(side="left")
        link_button(footer, "Sign in", lambda: self.app.navigate("login")).pack(
            side="left", padx=PAD_S)

    def on_show(self, **kwargs) -> None:
        for entry in (self._password, self._confirm):
            entry.delete(0, "end")
        self._name.focus_set()

    def _submit(self) -> None:
        # The confirm-password check is purely a GUI convenience; every real rule
        # (email format, length, unique email) is enforced by auth_service.
        if self._password.get() != self._confirm.get():
            self.app.show_message("Passwords don't match",
                                  "Please type the same password in both fields.")
            return
        self._button.configure(state="disabled")
        self.app.tasks.run(auth_service.register, self._name.get(), self._email.get(),
                           self._password.get(), on_success=self._registered,
                           on_error=self._failed, message="Creating your account...")

    def _registered(self, user) -> None:
        self._button.configure(state="normal")
        for entry in (self._name, self._email, self._password, self._confirm):
            entry.delete(0, "end")
        self.app.login(user)  # register() returns a logged-in session

    def _failed(self, error) -> None:
        self._button.configure(state="normal")
        self.app.show_error(error)
