"""The main window: sidebar on the left; top bar (title, loading indicator) and the
current screen on the right.

    +-----------+------------------------------------------------+
    | ShopSense | Title                          Loading... ~~~   |
    |           +------------------------------------------------+
    |  Shop     |                                                |
    |  Cart     |              current screen                    |
    |  Orders   |                                                |
    |  (user)   |                                                |
    |  Log out  |                                                |
    +-----------+------------------------------------------------+

Screens depend on who is logged in. Guests get Login / Register. On login, the
screens for that role are created; on logout they are destroyed, so nothing from one
user's session (cart, orders, typed text) can leak into the next one.
"""

import logging

import customtkinter as ctk

from app.gui import theme
from app.gui.screens.admin import AdminHomeScreen
from app.gui.screens.base import Screen
from app.gui.screens.cart import CartScreen
from app.gui.screens.login import LoginScreen
from app.gui.screens.orders import OrdersScreen
from app.gui.screens.product import ProductScreen
from app.gui.screens.register import RegisterScreen
from app.gui.screens.shop import ShopScreen
from app.gui.tasks import TaskRunner
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S
from app.gui.widgets.common import label, muted
from app.gui.widgets.dialogs import MessageDialog, show_error
from app.gui.widgets.sidebar import Sidebar
from app.gui.widgets.status import StatusIndicator
from app.services import system_service
from app.services.error_messages import friendly_error
from app.services.user_session import UserSession

log = logging.getLogger(__name__)

# (screen key, sidebar label, screen class). Screens not in a menu (product page) are
# still created for the role; they are reached by clicking, not from the sidebar.
GUEST_SCREENS = [("login", "Sign in", LoginScreen), ("register", "Create account", RegisterScreen)]
CUSTOMER_SCREENS = [("shop", "Shop", ShopScreen), ("cart", "Cart", CartScreen),
                    ("orders", "My Orders", OrdersScreen)]
CUSTOMER_HIDDEN_SCREENS = [("product", ProductScreen)]
ADMIN_SCREENS = [("admin", "Admin", AdminHomeScreen)]


class ShopSenseApp(ctk.CTk):
    def __init__(self) -> None:
        theme.apply_global_theme()
        super().__init__(fg_color=COLORS["bg"])
        self.title(theme.APP_NAME)
        self.minsize(*theme.MIN_WINDOW_SIZE)
        self._fit_to_screen()

        self.user: UserSession | None = None
        self.cart_coupon: str | None = None  # code applied in the cart (not stored in the DB)
        self.tasks = TaskRunner(self, on_busy_change=self._on_busy_change,
                                on_error=self.show_error)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.sidebar = Sidebar(self, on_navigate=self.navigate)
        self.sidebar.grid(row=0, column=0, sticky="nsw")

        main = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        self._build_top_bar(main)

        self._content = ctk.CTkFrame(main, fg_color=COLORS["bg"], corner_radius=0)
        self._content.grid(row=1, column=0, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        self._screens: dict[str, Screen] = {}
        self._current: str | None = None
        self._show_guest()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Wake the database up while the user is typing their password.
        self.after(100, lambda: self.tasks.run(system_service.check_connection,
                                               message="Connecting to database..."))

    # ------------------------------------------------------------------ layout

    def _fit_to_screen(self) -> None:
        """1280x800 centred if it fits; otherwise maximised (fills the screen above the
        taskbar). Screen sizes here are in the same scaled units as geometry()."""
        width, height = theme.WINDOW_SIZE
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        margin_w, margin_h = 40, 100  # room for the taskbar and title bar
        if width + margin_w <= screen_w and height + margin_h <= screen_h:
            x, y = (screen_w - width) // 2, (screen_h - height) // 3
            self.geometry(f"{width}x{height}+{x}+{y}")
        else:
            self.geometry(f"{min(width, screen_w - margin_w)}x{min(height, screen_h - margin_h)}+0+0")
            self.after(0, lambda: self.state("zoomed"))  # Windows: maximise

    def _build_top_bar(self, parent) -> None:
        bar = ctk.CTkFrame(parent, fg_color=COLORS["bg"], corner_radius=0, height=72)
        bar.grid(row=0, column=0, sticky="ew", padx=PAD_L, pady=(PAD_M, PAD_S))
        bar.grid_columnconfigure(1, weight=1)
        self._title = ctk.CTkLabel(bar, text="", font=theme.title_font(),
                                   text_color=COLORS["text"])
        self._title.grid(row=0, column=0, sticky="w")
        self.status = StatusIndicator(bar)
        self.status.grid(row=0, column=2, sticky="e")

    # ------------------------------------------------------------------ screens

    def _set_screens(self, visible: list[tuple], hidden: list[tuple] = ()) -> None:
        """Destroy the current screens and create these ones."""
        for screen in self._screens.values():
            screen.destroy()
        self._screens.clear()
        self._current = None
        for key, _label, cls in visible:
            self._add_screen(key, cls)
        for key, cls in hidden:
            self._add_screen(key, cls)
        self.sidebar.set_items([(key, text) for key, text, _cls in visible])

    def _add_screen(self, key: str, cls) -> None:
        screen = cls(self._content, self)
        screen.grid(row=0, column=0, sticky="nsew")
        screen.grid_remove()  # hidden until navigated to
        self._screens[key] = screen

    def _show_guest(self, email: str = "") -> None:
        self._set_screens(GUEST_SCREENS)
        self._set_footer()
        self.navigate("login", email=email)

    def navigate(self, key: str, **kwargs) -> None:
        """Show screen `key`; kwargs are passed to its on_show()."""
        if key not in self._screens:
            log.warning("No screen %r for this user", key)
            return
        if self._current is not None:
            self._screens[self._current].grid_remove()
        screen = self._screens[key]
        screen.grid()
        self._current = key
        self._title.configure(text=screen.title)
        self.sidebar.set_active(key)
        screen.on_show(**kwargs)

    # ------------------------------------------------------------------ session

    def login(self, user: UserSession) -> None:
        """Called by the login / register screens with the logged-in user."""
        self.user = user
        self.cart_coupon = None
        if user.is_admin:
            self._set_screens(ADMIN_SCREENS)
            start = "admin"
        else:
            self._set_screens(CUSTOMER_SCREENS, CUSTOMER_HIDDEN_SCREENS)
            start = "shop"
        self._set_footer()
        self.navigate(start)

    def logout(self) -> None:
        email = self.user.email if self.user else ""
        self.user = None
        self.cart_coupon = None
        self._show_guest(email)

    def _set_footer(self) -> None:
        footer = self.sidebar.footer
        for child in footer.winfo_children():
            child.destroy()
        if self.user is None:
            return
        ctk.CTkFrame(footer, height=1, fg_color=COLORS["border"]).pack(fill="x", pady=(0, PAD_M))
        label(footer, self.user.name, size=13, weight="bold").pack(fill="x", padx=PAD_S)
        muted(footer, self.user.email, size=11).pack(fill="x", padx=PAD_S)
        if self.user.is_admin:
            muted(footer, "Administrator", size=11).pack(fill="x", padx=PAD_S)
        ctk.CTkButton(footer, text="Log out", command=self.logout,
                      **{**theme.secondary_button_style(), "height": 34}).pack(
            fill="x", pady=(PAD_S, 0))

    # ------------------------------------------------------------------ feedback

    def _on_busy_change(self, message: str | None) -> None:
        self.status.set_busy(message)

    def show_error(self, error: BaseException) -> None:
        """Default handler for failed background tasks: a friendly popup."""
        info = friendly_error(error)
        show_error(self, info.title, info.message)

    def show_message(self, title: str, message: str, kind: str = "info") -> None:
        MessageDialog(self, title, message, kind=kind)

    def _on_close(self) -> None:
        self.tasks.shutdown()
        self.destroy()
