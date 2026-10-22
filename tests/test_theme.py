"""Light / dark mode: the colour palette, the saved preference, and switching the
running app (CTk widgets, the ttk table, matplotlib charts, the header toggle).

The GUI tests use the shared hidden window (conftest.gui_app) and always switch back to
light mode afterwards, so the other GUI tests are unaffected."""

import ast
import json
import re
from decimal import Decimal
from pathlib import Path
from tkinter import ttk

import pytest

from app.gui import preferences, theme
from app.gui.theme import COLORS

ROOT = Path(__file__).resolve().parent.parent
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

def _luminance(color: str) -> float:
    """WCAG relative luminance of a #RRGGBB colour."""
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio, 1 (none) to 21 (black on white)."""
    light, dark = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_every_colour_is_a_light_dark_pair_of_hex_colours():
    for key, value in COLORS.items():
        assert isinstance(value, tuple) and len(value) == 2, key
        assert all(HEX.match(c) for c in value), key
    for _glyph, tint in [*theme.CATEGORY_STYLE.values(), theme.DEFAULT_CATEGORY_STYLE]:
        assert len(tint) == 2 and all(HEX.match(c) for c in tint)


# (foreground, background, minimum contrast). 4.5 is WCAG AA for body text; 3 for
# large / bold text and UI parts (white bold labels on coloured buttons, muted hints).
READABLE = [
    ("text", "bg", 4.5), ("text", "surface", 4.5), ("text", "surface_hover", 4.5),
    ("text", "selected_nav", 4.5), ("text", "chip_selected", 4.5),
    ("text_muted", "surface", 3), ("text_muted", "bg", 3),
    ("accent", "surface", 3), ("accent", "selected_nav", 3),
    ("success", "surface", 3), ("danger", "surface", 3), ("warning", "surface", 2),
    # Header text is large (20 px logo, 14 px links): 3 is enough, and keeps
    # Flipkart's exact blue (white on #2874F0 is 4.3).
    ("header_text", "header", 3), ("header_muted", "header", 3),
    ("on_color", "accent", 3), ("on_color", "danger", 3),
]


@pytest.mark.parametrize("mode", [0, 1], ids=["light", "dark"])
@pytest.mark.parametrize("fg, bg, minimum", READABLE)
def test_text_stays_readable_in_both_modes(mode, fg, bg, minimum):
    ratio = contrast(COLORS[fg][mode], COLORS[bg][mode])
    assert ratio >= minimum, f"{fg} on {bg}: {ratio:.2f} < {minimum}"


def test_category_tiles_keep_icons_visible_in_both_modes():
    for mode in (0, 1):
        for _glyph, tint in theme.CATEGORY_STYLE.values():
            assert contrast(COLORS["text_muted"][mode], tint[mode]) >= 2.5


def test_gui_code_has_no_hard_coded_colours():
    """Colours belong in theme.py, as light / dark pairs. A hex literal anywhere else
    in the GUI would stay the same in both modes (e.g. dark text on a dark panel)."""
    offenders = []
    for path in sorted((ROOT / "app" / "gui").rglob("*.py")):
        if path.name == "theme.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and re.fullmatch(r"#[0-9A-Fa-f]{3,8}", node.value):
                offenders.append(f"{path.name}:{node.lineno} {node.value}")
    assert not offenders, offenders


# ---------------------------------------------------------------------------
# Mode helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def restore_mode():
    yield
    theme.set_mode(theme.LIGHT)


def test_resolve_picks_the_half_for_the_current_mode(restore_mode):
    theme.set_mode(theme.LIGHT)
    assert theme.resolve(("#111111", "#EEEEEE")) == "#111111"
    theme.set_mode(theme.DARK)
    assert theme.current_mode() == "dark"
    assert theme.resolve(("#111111", "#EEEEEE")) == "#EEEEEE"
    assert theme.resolve("#123456") == "#123456"   # single colours pass through


def test_set_mode_rejects_unknown_modes():
    with pytest.raises(ValueError):
        theme.set_mode("sepia")


def test_apply_global_theme_uses_the_saved_mode_or_falls_back_to_light(restore_mode):
    theme.apply_global_theme("dark")
    assert theme.current_mode() == "dark"
    theme.apply_global_theme("nonsense")
    assert theme.current_mode() == "light"


def test_other_mode():
    assert theme.other_mode("light") == "dark" and theme.other_mode("dark") == "light"


# ---------------------------------------------------------------------------
# Preference file
# ---------------------------------------------------------------------------

@pytest.fixture
def prefs_file(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "preferences.json"
    monkeypatch.setenv(preferences.ENV_VAR, str(path))
    return path


def test_default_is_light_when_nothing_is_saved(prefs_file):
    assert preferences.preferences_path() == prefs_file
    assert preferences.load_theme() == "light"


def test_saved_theme_is_loaded_again(prefs_file):
    preferences.save_theme("dark")
    assert json.loads(prefs_file.read_text(encoding="utf-8")) == {"theme": "dark"}
    assert preferences.load_theme() == "dark"
    preferences.save_theme("light")
    assert preferences.load_theme() == "light"


def test_saving_keeps_other_preferences(prefs_file):
    prefs_file.parent.mkdir(parents=True)
    prefs_file.write_text('{"window": "zoomed"}', encoding="utf-8")
    preferences.save_theme("dark")
    assert json.loads(prefs_file.read_text(encoding="utf-8")) == {"window": "zoomed",
                                                                  "theme": "dark"}


@pytest.mark.parametrize("content", ["not json {", '["dark"]', '{"theme": "purple"}', ""])
def test_corrupt_or_invalid_file_falls_back_to_light(prefs_file, content):
    prefs_file.parent.mkdir(parents=True)
    prefs_file.write_text(content, encoding="utf-8")
    assert preferences.load_theme() == "light"


def test_save_failure_is_logged_not_raised(tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "a_file"
    blocker.write_text("x", encoding="utf-8")
    # The "folder" is really a file, so the preferences can't be written.
    monkeypatch.setenv(preferences.ENV_VAR, str(blocker / "preferences.json"))
    preferences.save_theme("dark")
    assert "Could not save preferences" in caplog.text


def test_save_rejects_unknown_modes(prefs_file):
    with pytest.raises(ValueError):
        preferences.save_theme("sepia")
    assert not prefs_file.exists()


def test_default_location_is_in_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv(preferences.ENV_VAR, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert preferences.preferences_path() == tmp_path / "ShopSense" / "preferences.json"


# ---------------------------------------------------------------------------
# Switching the running app
# ---------------------------------------------------------------------------

@pytest.fixture
def window(gui_app):
    yield gui_app
    gui_app.set_theme("light")


def _saved() -> dict:
    return json.loads(preferences.preferences_path().read_text(encoding="utf-8"))


def test_app_starts_in_light_mode_with_a_dark_toggle(window):
    assert theme.current_mode() == "light"
    assert window.header.theme_toggle.cget("text") == "Dark"
    assert window.header.theme_toggle.winfo_manager() == "pack"


def test_toggle_label_follows_the_mode_whoever_changes_it(window):
    theme.set_mode("dark")   # not through the app (e.g. a test or future setting)
    assert window.header.theme_toggle.cget("text") == "Light"
    theme.set_mode("light")
    assert window.header.theme_toggle.cget("text") == "Dark"


def test_toggle_switches_mode_and_saves_it(window):
    window.header.theme_toggle.invoke()   # a click on the header's "Dark" button
    window.update()
    assert theme.current_mode() == "dark"
    assert window.header.theme_toggle.cget("text") == "Light"
    assert _saved() == {"theme": "dark"}

    window.header.theme_toggle.invoke()   # and back
    window.update()
    assert theme.current_mode() == "light"
    assert window.header.theme_toggle.cget("text") == "Dark"
    assert _saved() == {"theme": "light"}


def test_ctk_widgets_redraw_in_the_new_mode(window):
    title = window._title._label   # the real Tk label inside the CTk page title
    window.set_theme("dark")
    window.update()
    assert window.cget("bg") == COLORS["bg"][1]
    assert title.cget("fg") == COLORS["text"][1]
    window.set_theme("light")
    window.update()
    assert window.cget("bg") == COLORS["bg"][0]
    assert title.cget("fg") == COLORS["text"][0]


def test_table_restyles_its_ttk_treeview(window):
    from app.gui.widgets.table import STYLE, Column, DataTable

    table = DataTable(window, [Column("Name", 100, lambda r: r[1])])
    table.set_items([(1, "a")], key=lambda r: r[0])
    style = ttk.Style(window)
    try:
        window.set_theme("dark")
        assert style.lookup(STYLE, "background") == COLORS["surface"][1]
        assert style.lookup(STYLE, "foreground") == COLORS["text"][1]
        assert style.lookup(f"{STYLE}.Heading", "background") == COLORS["surface_hover"][1]
        assert str(table.tree.tag_configure("danger", "foreground")) == COLORS["danger"][1]
        window.set_theme("light")
        assert style.lookup(STYLE, "background") == COLORS["surface"][0]
        assert str(table.tree.tag_configure("danger", "foreground")) == COLORS["danger"][0]
    finally:
        table.destroy()


def test_chart_redraws_its_data_in_the_new_colours(window):
    from matplotlib.colors import to_hex

    from app.gui.widgets import charts

    card = charts.ChartCard(window, "Test chart", height=120)
    painted = []
    bars = charts.horizontal_bars(["Books", "Clothing"], [Decimal("10"), Decimal("20")])

    def painter(figure):
        painted.append(theme.current_mode())
        bars(figure)
    try:
        card.draw(painter)
        window.set_theme("dark")
        surface = COLORS["surface"][1]
        assert painted == ["light", "dark"]   # same data drawn again, no new query
        assert to_hex(card.figure.get_facecolor()).upper() == surface
        assert to_hex(card.figure.axes[0].get_facecolor()).upper() == surface
        assert card.canvas.get_tk_widget().cget("background") == surface
        tick = card.figure.axes[0].get_yticklabels()[0]
        assert to_hex(tick.get_color()).upper() == COLORS["text_muted"][1]
    finally:
        card.destroy()


def test_every_widget_on_the_guest_screens_restyles_without_errors(window,
                                                                   strict_theme_switch):
    for key in ("login", "register"):
        window.navigate(key)
        window.set_theme("dark")
        window.update()
        window.set_theme("light")
        window.update()
