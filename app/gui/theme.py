"""Colours, fonts and spacing used by every screen, so the whole app looks consistent.

Change a value here and it changes everywhere. Screens should never hard-code colours.
"""

import customtkinter as ctk

APP_NAME = "ShopSense"
# Preferred size. On small screens the window starts maximised instead (see app.py):
# a 1920x1080 laptop at 150 % scaling is only 1280x720 in these logical units.
WINDOW_SIZE = (1280, 800)
MIN_WINDOW_SIZE = (960, 600)
STATUS_WIDTH = 380  # fixed slot for the loading indicator, so the search box never moves
SIDEBAR_WIDTH = 220

# Dark palette: near-black background, slightly lighter "surfaces" for cards and the
# sidebar, one accent colour for primary actions.
COLORS = {
    "bg": "#0F1115",
    "sidebar": "#151821",
    "surface": "#1B1F2A",
    "surface_hover": "#242A38",
    "border": "#2A3040",
    "text": "#E6E8EE",
    "text_muted": "#9AA3B2",
    "accent": "#6C8CFF",
    "accent_hover": "#5A78E8",
    "danger": "#F06A6A",
    "success": "#4CC38A",
    "warning": "#F2C14E",
}

# Spacing scale (pixels). Use these instead of random numbers so gaps line up.
PAD_XS, PAD_S, PAD_M, PAD_L, PAD_XL = 4, 8, 16, 24, 32
CORNER_RADIUS = 10

FONT_FAMILY = "Segoe UI"  # Windows system font; Tk falls back to a default elsewhere


def font(size: int = 14, weight: str = "normal") -> ctk.CTkFont:
    """Fonts can only be created after the main window exists, hence a function."""
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


# Named text styles, so headings look the same on every screen.
def title_font() -> ctk.CTkFont:
    return font(22, "bold")


def heading_font() -> ctk.CTkFont:
    return font(16, "bold")


def body_font() -> ctk.CTkFont:
    return font(14)


def small_font() -> ctk.CTkFont:
    return font(12)


def apply_global_theme() -> None:
    """Call once, before creating the main window."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")


def primary_button_style() -> dict:
    return {"fg_color": COLORS["accent"], "hover_color": COLORS["accent_hover"],
            "text_color": "#FFFFFF", "text_color_disabled": "#2A3566",
            "corner_radius": CORNER_RADIUS, "height": 38,
            "font": font(14, "bold")}


def secondary_button_style() -> dict:
    return {"fg_color": COLORS["surface"], "hover_color": COLORS["surface_hover"],
            "text_color": COLORS["text"], "border_color": COLORS["border"], "border_width": 1,
            "corner_radius": CORNER_RADIUS, "height": 38, "font": font(14)}
