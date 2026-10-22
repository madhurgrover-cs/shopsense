"""The blue bar across the top of the window, in Flipkart's style:

    +---------------------------------------------------------------------------------+
    | ShopSense     [ Search for products, brands and more      (Q)]  Loading ~~~      |
    | AI search ready                                   (o) Tara Dhar  [] Orders  Cart |
    +---------------------------------------------------------------------------------+

What it shows depends on who is logged in (set_user):
- guests: the logo only;
- customers: logo + AI search status, the search box, and Account / Orders / Cart links;
- admins: logo + "Seller Hub", and the admin's name with a Log out link (no search).

Everyone (guests too) gets the light / dark mode toggle at the far right. It shows the
mode it switches TO: a moon and "Dark" in light mode, a sun and "Light" in dark mode.

The header only reports clicks (on_search, on_navigate, on_logout, on_toggle_theme);
app.py decides what they do.
"""

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, CORNER_RADIUS, HEADER_HEIGHT, ICONS, PAD_L, PAD_S, PAD_XL
from app.gui.widgets.status import StatusIndicator
from app.services.user_session import UserSession


class Header(ctk.CTkFrame):
    def __init__(self, parent, on_search: Callable[[str], None],
                 on_navigate: Callable[[str], None], on_logout: Callable[[], None],
                 on_toggle_theme: Callable[[], None]) -> None:
        super().__init__(parent, fg_color=COLORS["header"], corner_radius=0,
                         height=HEADER_HEIGHT)
        self.grid_propagate(False)  # fixed height
        self._on_search, self._on_navigate, self._on_logout = on_search, on_navigate, on_logout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Logo: white italic bold name, with a small italic line under it (like
        # Flipkart's "Explore Plus"): "Seller Hub" for admins; for customers, the AI
        # search status (ai_status, set by app.py while the model loads).
        logo = ctk.CTkFrame(self, fg_color="transparent")
        logo.grid(row=0, column=0, sticky="w", padx=(PAD_XL, PAD_L))
        ctk.CTkLabel(logo, text=theme.APP_NAME, font=theme.font(20, "bold", "italic"),
                     text_color=COLORS["header_text"], height=24).pack(anchor="w")
        self.subtitle = ctk.CTkLabel(logo, text="", font=theme.font(11, "normal", "italic"),
                                     text_color=COLORS["header_muted"], height=14)
        self.subtitle.pack(anchor="w")
        self.ai_status = ctk.CTkLabel(logo, text="", font=theme.font(11, "normal", "italic"),
                                      text_color=COLORS["header_muted"], height=14)
        self.ai_status.pack(anchor="w")

        # Search box: wide and white, with the search icon button at its right end.
        self._search_box = ctk.CTkFrame(self, fg_color=COLORS["surface"],
                                        corner_radius=CORNER_RADIUS, height=36)
        self._search_box.grid_columnconfigure(0, weight=1)
        self.search = ctk.CTkEntry(
            self._search_box, height=36, border_width=0, corner_radius=CORNER_RADIUS,
            fg_color=COLORS["surface"], text_color=COLORS["text"], font=theme.font(14),
            placeholder_text="Search for products, or describe what you need",
            placeholder_text_color=COLORS["text_muted"])
        self.search.grid(row=0, column=0, sticky="ew", padx=(PAD_S, 0))
        self.search.bind("<Return>", lambda _e: self._search())
        ctk.CTkButton(self._search_box, text=ICONS["search"], width=40, height=36,
                      font=theme.icon_font(16), fg_color=COLORS["surface"],
                      hover_color=COLORS["surface_hover"], text_color=COLORS["accent"],
                      corner_radius=CORNER_RADIUS, command=self._search).grid(row=0, column=1)

        self.status = StatusIndicator(self, on_dark=True)
        self.status.grid(row=0, column=2, sticky="e", padx=(PAD_L, 0))

        self._links = ctk.CTkFrame(self, fg_color="transparent")
        self._links.grid(row=0, column=3, sticky="e", padx=(PAD_S, 0))
        self._link_buttons: dict[str, ctk.CTkButton] = {}
        self._menu: tk.Menu | None = None

        # Light / dark toggle: always visible, whoever is logged in. Built like the
        # other header links (icon-font glyph + text button), both parts clickable.
        toggle = ctk.CTkFrame(self, fg_color="transparent")
        toggle.grid(row=0, column=4, sticky="e", padx=(PAD_L, PAD_XL))
        self.theme_icon = ctk.CTkLabel(toggle, text="", font=theme.icon_font(15),
                                       text_color=COLORS["header_text"], width=18,
                                       cursor="hand2")
        self.theme_icon.pack(side="left")
        self.theme_icon.bind("<Button-1>", lambda _e: on_toggle_theme())
        self.theme_toggle = ctk.CTkButton(
            toggle, text="", command=on_toggle_theme, width=0, height=30,
            fg_color="transparent", hover_color=COLORS["accent_hover"],
            text_color=COLORS["header_text"], font=theme.font(14),
            corner_radius=CORNER_RADIUS)
        self.theme_toggle.pack(side="left")
        self.set_theme_mode(theme.current_mode())

    def _set_appearance_mode(self, mode_string: str) -> None:
        """CustomTkinter calls this when the light / dark mode changes, so the toggle's
        label always matches the mode actually in use, whoever switched it."""
        super()._set_appearance_mode(mode_string)
        self.set_theme_mode(mode_string.lower())

    def set_theme_mode(self, mode: str) -> None:
        """Label the toggle with the mode a click will switch to."""
        target = theme.other_mode(mode)
        self.theme_icon.configure(
            text=theme.ICONS["dark_mode" if target == theme.DARK else "light_mode"])
        self.theme_toggle.configure(text=target.capitalize())

    # ------------------------------------------------------------------ who is logged in

    def set_user(self, user: UserSession | None) -> None:
        for child in self._links.winfo_children():
            child.destroy()
        self._link_buttons.clear()
        self.search.delete(0, "end")
        is_customer = user is not None and not user.is_admin
        if is_customer:
            self._search_box.grid(row=0, column=1, sticky="ew", padx=PAD_S)
        else:
            self._search_box.grid_forget()
        self.subtitle.configure(text="Seller Hub" if user and user.is_admin else "")
        # Pack only the line in use, so the logo stays vertically centred.
        if user is not None and user.is_admin:
            self.subtitle.pack(anchor="w", before=self.ai_status)
            self.ai_status.pack_forget()
        else:
            self.subtitle.pack_forget()
            self.ai_status.pack(anchor="w")
        if user is None:
            return
        if user.is_admin:
            self._link(ICONS["account"], user.name, None)
            self._link(None, "Log out", self._on_logout)
        else:
            self._link(ICONS["account"], user.name.split()[0],
                       lambda: self._account_menu(user), key="account")
            self._link(ICONS["orders"], "Orders", lambda: self._on_navigate("orders"),
                       key="orders")
            self._link(ICONS["cart"], "Cart", lambda: self._on_navigate("cart"), key="cart")

    def set_active(self, key: str | None) -> None:
        """Underline-free emphasis on the link of the screen being shown."""
        for link_key, button in self._link_buttons.items():
            button.configure(font=theme.font(14, "bold" if link_key == key else "normal"))

    def _link(self, glyph: str | None, text: str, command, key: str | None = None) -> None:
        if glyph:
            icon = ctk.CTkLabel(self._links, text=glyph, font=theme.icon_font(15),
                                text_color=COLORS["header_text"], width=18)
            icon.pack(side="left", padx=(PAD_L, 0))
            if command:
                icon.bind("<Button-1>", lambda _e: command())
                icon.configure(cursor="hand2")
        if command is None:  # plain text (the admin's name)
            ctk.CTkLabel(self._links, text=text, font=theme.font(14, "bold"),
                         text_color=COLORS["header_text"]).pack(side="left", padx=(4, 0))
            return
        button = ctk.CTkButton(self._links, text=text, command=command, width=0, height=30,
                               fg_color="transparent", hover_color=COLORS["accent_hover"],
                               text_color=COLORS["header_text"], font=theme.font(14),
                               corner_radius=CORNER_RADIUS)
        button.pack(side="left", padx=(0 if glyph else PAD_L, 0))
        if key:
            self._link_buttons[key] = button

    def _account_menu(self, user: UserSession) -> None:
        """A small drop-down under "Account": who is signed in, My Orders, Log out."""
        if self._menu is not None:
            self._menu.destroy()
        # tk.Menu is plain Tk: give it single colours for the current mode. It is
        # rebuilt on every click, so it always matches the mode in use.
        c = {key: theme.resolve(value) for key, value in COLORS.items()}
        menu = tk.Menu(self, tearoff=0, font=(theme.font_family(), 10),
                       bg=c["surface"], fg=c["text"], disabledforeground=c["text_muted"],
                       activebackground=c["selected_nav"],
                       activeforeground=c["accent"], relief="flat", borderwidth=1)
        menu.add_command(label=user.email, state="disabled")
        menu.add_separator()
        menu.add_command(label="My Orders", command=lambda: self._on_navigate("orders"))
        menu.add_command(label="Log out", command=self._on_logout)
        self._menu = menu
        anchor = self._link_buttons["account"]
        menu.tk_popup(anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height())

    def _search(self) -> None:
        query = self.search.get().strip()
        if query:
            self._on_search(query)
