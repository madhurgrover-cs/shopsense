"""Colours, fonts, icons and spacing used by every screen, so the whole app looks
consistent. Change a value here and it changes everywhere; screens never hard-code
colours.

The look follows Flipkart's design language: a light grey page, flat white panels with
thin borders, a blue header, orange buy buttons, green rating pills, nearly square
corners and dense spacing. No gradients or shadows.

Light and dark mode
-------------------
Every colour in COLORS is a (light, dark) pair. That is CustomTkinter's own format:
a CTk widget given a pair draws whichever half matches the current appearance mode,
and redraws itself when ctk.set_appearance_mode() changes it. So switching mode
(set_mode below) re-colours every CTk widget in the app with no per-screen code.

Plain Tk / ttk widgets and matplotlib only understand ONE colour string. Code that
feeds them (the table, the charts, the account menu) calls resolve(COLORS[...]) to
get the half for the current mode, and re-applies its colours when the mode changes
(see DataTable / ChartCard._set_appearance_mode).
"""

import tkinter.font as tkfont

import customtkinter as ctk

APP_NAME = "ShopSense"
# Preferred size. On small screens the window starts maximised instead (see app.py):
# a 1920x1080 laptop at 150 % scaling is only 1280x720 in these logical units.
WINDOW_SIZE = (1280, 800)
MIN_WINDOW_SIZE = (960, 600)
STATUS_WIDTH = 300      # fixed slot for the loading indicator, so nothing else moves
HEADER_HEIGHT = 56
SIDEBAR_WIDTH = 200     # the admin's left navigation (customers have no sidebar)

LIGHT, DARK = "light", "dark"
MODES = (LIGHT, DARK)
DEFAULT_MODE = LIGHT

# (light mode, dark mode). The dark half keeps Flipkart's identity (blue header,
# orange buy buttons, green pills) on near-black panels: the page is the darkest
# layer and panels are slightly lighter, the same layering as light mode.
COLORS = {
    # Page and panels
    "bg": ("#F1F3F6", "#121417"),             # page background
    "surface": ("#FFFFFF", "#1E2125"),        # flat panels
    "surface_hover": ("#F5F7FA", "#2A2E34"),  # hover highlight
    "sidebar": ("#FFFFFF", "#1E2125"),
    "selected_nav": ("#F0F5FF", "#1E2D47"),   # selected row / nav item
    "chip_selected": ("#D4E3FC", "#2C4673"),  # the chosen option of a segmented button
    "border": ("#E0E0E0", "#363A41"),         # thin 1 px borders
    # Text
    "text": ("#212121", "#E8EAED"),
    "text_muted": ("#878787", "#9AA0A6"),
    # Header (blue in both modes; a deeper navy in dark mode so it doesn't glare)
    "header": ("#2874F0", "#1A3A6E"),
    "header_text": ("#FFFFFF", "#FFFFFF"),
    "header_muted": ("#D6E4FC", "#B3C8EC"),   # secondary text on the header
    # Actions and states. Dark-mode accents are a little lighter, so blue / green /
    # red text stays readable on dark panels; buttons keep white text in both modes.
    "accent": ("#2874F0", "#3D82F0"),         # links, selection, primary admin actions
    "accent_hover": ("#1F5FCC", "#2B6AD6"),
    "cart": ("#FF9F00", "#FF9F00"),           # ADD TO CART
    "cart_hover": ("#F09000", "#F09000"),
    "buy": ("#FB641B", "#FB641B"),            # BUY NOW / PLACE ORDER / LOGIN
    "buy_hover": ("#E85A15", "#E85A15"),
    "success": ("#388E3C", "#43A047"),        # rating pills, savings, "In stock", delivered
    "warning": ("#FF9F00", "#FFAD26"),
    "danger": ("#E53935", "#EF5350"),
    "danger_hover": ("#C62828", "#E53935"),
    "disabled": ("#C2C2C2", "#5F6368"),
    "on_color": ("#FFFFFF", "#FFFFFF"),       # text on coloured buttons and pills
}

# Matplotlib chart colours: Flipkart blue and orange first. Mid-tone colours that read
# on both a white and a dark chart background, so one list serves both modes.
CHART_COLORS = ["#2874F0", "#FF9F00", "#FB641B", "#388E3C", "#26A5E4", "#00897B",
                "#F9A825", "#878787"]


def current_mode() -> str:
    """"light" or "dark": the mode CustomTkinter is drawing in right now."""
    return ctk.get_appearance_mode().lower()


def resolve(color: str | tuple[str, str]) -> str:
    """One colour string for the current mode, for things that aren't CTk widgets
    (ttk styles, tk.Menu, matplotlib). Plain strings are returned unchanged."""
    if isinstance(color, (tuple, list)):
        return color[1] if current_mode() == DARK else color[0]
    return color


def set_mode(mode: str) -> None:
    """Switch the whole app to "light" or "dark" while it runs. CustomTkinter calls
    every widget's _set_appearance_mode(), so CTk widgets redraw themselves and our
    Tk-based widgets (table, charts) re-apply their resolved colours."""
    if mode not in MODES:
        raise ValueError(f"Unknown theme mode {mode!r}")
    ctk.set_appearance_mode(mode)


def other_mode(mode: str) -> str:
    return LIGHT if mode == DARK else DARK


# Spacing scale (pixels): tight inside groups, larger between groups.
PAD_XS, PAD_S, PAD_M, PAD_L, PAD_XL = 4, 6, 12, 16, 24
CORNER_RADIUS = 2   # nearly square, like Flipkart (never more than 4)

# Icons: glyphs from the Windows icon font (no emoji, no image files). "Segoe Fluent
# Icons" ships with Windows 11; Windows 10 has the older "Segoe MDL2 Assets", which uses
# the same code points for these glyphs.
ICONS = {
    "search": "", "cart": "", "account": "", "orders": "",
    "all": "", "bag": "", "back": "", "close": "",
    "dark_mode": "", "light_mode": "",  # moon / sun (theme toggle)
}
# Category name -> (icon, soft tile colour as a (light, dark) pair). The tile stands in
# for a product photo: pastel in light mode, a deep tint of the same hue in dark mode.
CATEGORY_STYLE = {
    "Mobiles & Accessories": ("", ("#E3F2FD", "#1A2A3B")),
    "Laptops & Computer Accessories": ("", ("#E0F7FA", "#16302F")),
    "Home & Kitchen": ("", ("#FFF3E0", "#33281A")),
    "Clothing": ("", ("#FCE4EC", "#33202A")),
    "Footwear": ("", ("#EFEBE9", "#2B2624")),
    "Books": ("", ("#FFFDE7", "#302D1A")),
    "Sports & Fitness": ("", ("#E8F5E9", "#1C2E1F")),
    "Beauty & Personal Care": ("", ("#FBE9E7", "#33231F")),
}
DEFAULT_CATEGORY_STYLE = ("", ("#ECEFF1", "#25292E"))


def category_style(name: str) -> tuple[str, tuple[str, str]]:
    """(icon glyph, tile colour pair) for a category; a neutral bag for unknown ones."""
    return CATEGORY_STYLE.get(name, DEFAULT_CATEGORY_STYLE)


# Fonts: Roboto (Flipkart's font) if installed, else Segoe UI. Decided once, after the
# main window exists (Tk can only list fonts then).
_families: dict[str, str] = {}


def _pick(key: str, preferred: list[str]) -> str:
    if key not in _families:
        installed = set(tkfont.families())
        _families[key] = next((f for f in preferred if f in installed), preferred[-1])
    return _families[key]


def font_family() -> str:
    return _pick("text", ["Roboto", "Segoe UI"])


def icon_family() -> str:
    return _pick("icon", ["Segoe Fluent Icons", "Segoe MDL2 Assets"])


def font(size: int = 13, weight: str = "normal", slant: str = "roman") -> ctk.CTkFont:
    """Fonts can only be created after the main window exists, hence a function."""
    return ctk.CTkFont(family=font_family(), size=size, weight=weight, slant=slant)


def icon_font(size: int = 16) -> ctk.CTkFont:
    return ctk.CTkFont(family=icon_family(), size=size)


# Named text styles, so headings look the same on every screen.
def title_font() -> ctk.CTkFont:
    return font(18, "bold")


def heading_font() -> ctk.CTkFont:
    return font(15, "bold")


def body_font() -> ctk.CTkFont:
    return font(13)


def small_font() -> ctk.CTkFont:
    return font(12)


def apply_global_theme(mode: str = DEFAULT_MODE) -> None:
    """Call once, before creating the main window, with the saved mode (see
    preferences.py). Later switches go through set_mode()."""
    ctk.set_appearance_mode(mode if mode in MODES else DEFAULT_MODE)
    ctk.set_default_color_theme("blue")
    # Thin scrollbars everywhere (the default ones are heavy): light grey in light
    # mode, dark grey in dark mode. Theme values are [light mode, dark mode] pairs.
    scrollbar = ctk.ThemeManager.theme["CTkScrollbar"]
    scrollbar["button_color"] = ["#C9CED6", "#4A4F57"]
    scrollbar["button_hover_color"] = ["#A9AFB8", "#626873"]


# Buttons. Flipkart's action buttons are flat, nearly square, white bold UPPERCASE text
# (callers write the label in upper case).
def _solid(color: str, hover: str, height: int = 40) -> dict:
    return {"fg_color": color, "hover_color": hover, "text_color": COLORS["on_color"],
            "text_color_disabled": COLORS["on_color"], "corner_radius": CORNER_RADIUS,
            "height": height, "border_width": 0, "font": font(14, "bold")}


def cart_button_style() -> dict:
    """ADD TO CART (orange)."""
    return _solid(COLORS["cart"], COLORS["cart_hover"], height=46)


def buy_button_style() -> dict:
    """BUY NOW / PLACE ORDER / LOGIN: the one main action on a customer screen."""
    return _solid(COLORS["buy"], COLORS["buy_hover"], height=46)


def primary_button_style() -> dict:
    """Blue: the main action on an admin screen."""
    return {**_solid(COLORS["accent"], COLORS["accent_hover"], height=34),
            "font": font(13, "bold")}


def secondary_button_style() -> dict:
    """Everything else: a panel-coloured button with a thin border, visually quieter."""
    return {"fg_color": COLORS["surface"], "hover_color": COLORS["surface_hover"],
            "text_color": COLORS["text"], "text_color_disabled": COLORS["disabled"],
            "border_color": COLORS["border"], "border_width": 1,
            "corner_radius": CORNER_RADIUS, "height": 34, "font": font(13)}


def segmented_style() -> dict:
    """Segmented buttons (7 / 30 / 90 days, payment method): panel-coloured options in
    a thin frame; the chosen one tinted blue. The text stays readable on both."""
    return {"fg_color": COLORS["border"], "selected_color": COLORS["chip_selected"],
            "selected_hover_color": COLORS["chip_selected"],
            "unselected_color": COLORS["surface"], "unselected_hover_color": COLORS["surface_hover"],
            "text_color": COLORS["text"], "corner_radius": CORNER_RADIUS, "border_width": 1,
            "height": 32}
