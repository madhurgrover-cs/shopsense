"""The main window: the blue header across the top, then the current screen. Admins
also get a slim navigation column on the left (a "seller dashboard"); customers
navigate with the header (search, Account, Orders, Cart) and the shop's category strip.

    Customer                                  Admin
    +-------------------------------------+   +--------------------------------------+
    | ShopSense [ search........ ] Cart   |   | ShopSense / Seller Hub   Admin Log out|
    +-------------------------------------+   +----------+---------------------------+
    | Page title (not on the shop)        |   | Dashboard| Page title                |
    |            current screen           |   | Products |     current screen        |
    +-------------------------------------+   +----------+---------------------------+

Screens depend on who is logged in. Guests get Login / Register, customers the shop,
admins their own navigation (dashboard, products, orders, ...). On login, the screens for
that role are created; on logout they are destroyed, so nothing from one user's
session (cart, orders, typed text) can leak into the next one.

Light / dark mode: the header's toggle calls toggle_theme(), which switches
CustomTkinter's appearance mode (every widget re-colours itself, see theme.py) and
saves the choice in a small local file (preferences.py), read again at the next start.
"""

import gc
import logging
import threading
from tkinter import filedialog

import customtkinter as ctk

from app.gui import preferences, theme
from app.gui.screens.admin.ask_data import AskDataScreen
from app.gui.screens.admin.audit import AuditLogScreen
from app.gui.screens.admin.coupons import CouponsScreen
from app.gui.screens.admin.dashboard import DashboardScreen
from app.gui.screens.admin.orders import AdminOrdersScreen
from app.gui.screens.admin.products import ProductsScreen
from app.gui.screens.admin.reports import ReportsScreen
from app.gui.screens.admin.reviews import FlaggedReviewsScreen
from app.gui.screens.admin.users import CustomersScreen
from app.gui.screens.base import Screen
from app.gui.screens.cart import CartScreen
from app.gui.screens.login import LoginScreen
from app.gui.screens.orders import OrdersScreen
from app.gui.screens.product import ProductScreen
from app.gui.screens.register import RegisterScreen
from app.gui.screens.shop import ShopScreen
from app.gui.tasks import TaskRunner
from app.gui.theme import COLORS, PAD_M, PAD_XL
from app.gui.widgets.dialogs import ConfirmDialog, MessageDialog, show_error
from app.gui.widgets.header import Header
from app.gui.widgets.sidebar import Sidebar
from app.services import system_service
from app.services.error_messages import friendly_error
from app.services.user_session import UserSession

log = logging.getLogger(__name__)

# (screen key, menu label, screen class). Screens not in a menu (product page) are
# still created for the role; they are reached by clicking, not from the sidebar.
GUEST_SCREENS = [("login", "Sign in", LoginScreen), ("register", "Create account", RegisterScreen)]
CUSTOMER_SCREENS = [("shop", "Shop", ShopScreen), ("cart", "Cart", CartScreen),
                    ("orders", "My Orders", OrdersScreen)]
CUSTOMER_HIDDEN_SCREENS = [("product", ProductScreen)]
ADMIN_SCREENS = [
    ("admin_dashboard", "Dashboard", DashboardScreen),
    ("admin_products", "Products", ProductsScreen),
    ("admin_orders", "Orders", AdminOrdersScreen),
    ("admin_coupons", "Coupons", CouponsScreen),
    ("admin_reviews", "Flagged reviews", FlaggedReviewsScreen),
    ("admin_reports", "Reports", ReportsScreen),
    ("admin_ask", "Ask your data", AskDataScreen),
    ("admin_users", "Customers", CustomersScreen),
    ("admin_audit", "Audit log", AuditLogScreen),
]

AI_POLL_MS = 500  # how often the main thread checks whether the AI model has loaded
# AI model state -> (text under the logo, colour key). The header is blue, so the
# colours are white / pale blue rather than green / orange.
AI_STATUS = {
    "loading": ("Loading AI search...", "header_muted"),
    "ready": ("● AI search ready", "header_text"),
    "failed": ("AI search unavailable, using keywords", "header_muted"),
}


class ShopSenseApp(ctk.CTk):
    def __init__(self) -> None:
        # The saved light / dark mode must be set BEFORE any widget exists, so the
        # window opens in it (no flash of the other mode).
        theme.apply_global_theme(preferences.load_theme())
        super().__init__(fg_color=COLORS["bg"])
        self.title(theme.APP_NAME)
        self.minsize(*theme.MIN_WINDOW_SIZE)
        self._fit_to_screen()

        self.user: UserSession | None = None
        self.cart_coupon: str | None = None  # code applied in the cart (not stored in the DB)
        self.export_folder: str | None = None  # last folder reports were saved to
        self.tasks = TaskRunner(self, on_busy_change=self._on_busy_change,
                                on_error=self.show_error)
        self._ai_loader: threading.Thread | None = None
        self._ai_loaded_ok = False
        self._ai_poll: str | None = None  # id of the scheduled after() check

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.header = Header(self, on_search=self._search, on_navigate=self.navigate,
                             on_logout=self.logout, on_toggle_theme=self.toggle_theme)
        self.header.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.status = self.header.status
        self._ai_status = self.header.ai_status  # the small line under the logo
        # Admins only (see _show_sidebar).
        self.sidebar = Sidebar(self, on_navigate=self.navigate)

        main = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        main.grid(row=1, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        # Page title: a slim line above the screen. Hidden on screens that start with
        # their own heading (shop, login, register): see Screen.show_title.
        self._title = ctk.CTkLabel(main, text="", font=theme.title_font(),
                                   text_color=COLORS["text"], anchor="w")
        self._title.grid(row=0, column=0, sticky="ew", padx=PAD_XL, pady=(PAD_M, 0))

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

    def _show_sidebar(self, visible: bool) -> None:
        if visible:
            self.sidebar.grid(row=1, column=0, sticky="nsw")
        else:
            self.sidebar.grid_remove()

    # ------------------------------------------------------------------ screens

    def _set_screens(self, visible: list[tuple], hidden: list[tuple] = ()) -> None:
        """Destroy the current screens and create these ones."""
        for screen in self._screens.values():
            screen.destroy()
        self._screens.clear()
        self._current = None
        # Free the destroyed screens NOW, on the main thread. Otherwise Python's garbage
        # collector frees them later on whichever thread happens to be allocating, often
        # a background task (e.g. building a PDF), and Tk objects must only be touched
        # from the main thread: tkinter then waits ~1 s per object for the main thread.
        gc.collect()
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
        self._show_sidebar(False)
        self.header.set_user(None)
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
        if screen.show_title:
            self._title.grid()
        else:
            self._title.grid_remove()
        self.sidebar.set_active(key)
        self.header.set_active(key)
        screen.on_show(**kwargs)

    def _search(self, query: str) -> None:
        """The header's search box: results are shown on the shop screen."""
        self.navigate("shop", search=query)

    # ------------------------------------------------------------------ session

    def login(self, user: UserSession) -> None:
        """Called by the login / register screens with the logged-in user."""
        self.user = user
        self.cart_coupon = None
        if user.is_admin:
            self._set_screens(ADMIN_SCREENS)
            start = "admin_dashboard"
        else:
            self._set_screens(CUSTOMER_SCREENS, CUSTOMER_HIDDEN_SCREENS)
            start = "shop"
        self._show_sidebar(user.is_admin)
        self.header.set_user(user)
        self.navigate(start)
        if not user.is_admin:
            self._preload_search_model()

    def logout(self) -> None:
        email = self.user.email if self.user else ""
        self.user = None
        self.cart_coupon = None
        self._stop_ai_poll()
        self._set_ai_status(None)
        self._show_guest(email)

    # ------------------------------------------------------------------ AI model

    def _preload_search_model(self) -> None:
        """Start loading the AI search model in the background right after a customer
        logs in, so their first search is fast instead of waiting ~30 s.

        It uses its own thread rather than self.tasks: the load takes ~30 s and would
        otherwise block one of the two task workers (and the loading indicator) the
        whole time. If the user searches before it finishes, the search simply waits
        for the same load (embeddings.get_model uses a lock); it never loads twice.
        """
        self._stop_ai_poll()
        if system_service.is_search_model_loaded():
            self._set_ai_status("ready")
            return
        if self._ai_loader is None or not self._ai_loader.is_alive():
            self._ai_loader = threading.Thread(target=self._load_model, daemon=True,
                                               name="shopsense-ai-preload")
            self._ai_loader.start()
        self._set_ai_status("loading")
        self._ai_poll = self.after(AI_POLL_MS, self._check_model_loaded)

    def _load_model(self) -> None:
        # Runs in the preload thread: no Tkinter calls allowed here.
        self._ai_loaded_ok = system_service.preload_search_model()

    def _check_model_loaded(self) -> None:
        """Main thread, every AI_POLL_MS until the preload thread has finished."""
        if self._ai_loader.is_alive():
            self._ai_poll = self.after(AI_POLL_MS, self._check_model_loaded)
            return
        self._ai_poll = None
        self._set_ai_status("ready" if self._ai_loaded_ok else "failed")

    def _stop_ai_poll(self) -> None:
        if self._ai_poll is not None:
            self.after_cancel(self._ai_poll)
            self._ai_poll = None

    def _set_ai_status(self, state: str | None) -> None:
        text, color = AI_STATUS.get(state, ("", "text_muted"))
        self._ai_status.configure(text=text, text_color=COLORS[color])

    # ------------------------------------------------------------------ theme

    def toggle_theme(self) -> None:
        """The header's Dark / Light button: switch mode and remember it."""
        self.set_theme(theme.other_mode(theme.current_mode()))

    def set_theme(self, mode: str) -> None:
        """Switch the running app to "light" or "dark" (no restart needed) and save it.
        Widgets re-colour themselves (and the header relabels its toggle) through
        CustomTkinter's appearance-mode callbacks."""
        theme.set_mode(mode)
        preferences.save_theme(mode)

    # ------------------------------------------------------------------ feedback

    def _on_busy_change(self, message: str | None) -> None:
        self.status.set_busy(message)

    def show_error(self, error: BaseException) -> None:
        """Default handler for failed background tasks: a friendly popup."""
        info = friendly_error(error)
        show_error(self, info.title, info.message)

    def show_message(self, title: str, message: str, kind: str = "info") -> None:
        MessageDialog(self, title, message, kind=kind)

    def confirm(self, title: str, message: str, on_confirm, confirm_text: str = "Confirm",
                danger: bool = True) -> None:
        """Ask "are you sure?"; on_confirm() runs only if the user confirms."""
        ConfirmDialog(self, title, message, on_confirm, confirm_text=confirm_text,
                      danger=danger)

    def ask_folder(self, title: str) -> str:
        """Let the user pick a folder (e.g. for report exports). "" if they cancel."""
        folder = filedialog.askdirectory(parent=self, title=title, mustexist=True,
                                         initialdir=self.export_folder or None)
        if folder:
            self.export_folder = folder
        return folder or ""

    def _on_close(self) -> None:
        self.tasks.shutdown()
        self.destroy()
