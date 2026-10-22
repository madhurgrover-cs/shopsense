"""Small per-user GUI preferences (currently just light / dark mode), saved as JSON on
this computer, NOT in the database: they are about this desktop, not shop data, and
need no login.

Where the file lives:
- Windows: %APPDATA%\\ShopSense\\preferences.json
- elsewhere: ~/.config/shopsense/preferences.json
- the SHOPSENSE_PREFS_FILE environment variable overrides both (tests use it, so they
  never touch the real file).

A missing, unreadable or corrupt file is never an error: the app just starts in the
default mode. Failing to save is logged, not shown: the theme still switches, it only
won't be remembered.
"""

import json
import logging
import os
from pathlib import Path

from app.gui import theme

log = logging.getLogger(__name__)

ENV_VAR = "SHOPSENSE_PREFS_FILE"
THEME_KEY = "theme"


def preferences_path() -> Path:
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "ShopSense" / "preferences.json"
    return Path.home() / ".config" / "shopsense" / "preferences.json"


def _load() -> dict:
    try:
        data = json.loads(preferences_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):  # no file yet, or not valid JSON
        return {}
    return data if isinstance(data, dict) else {}


def load_theme() -> str:
    """The saved mode ("light" / "dark"), or the default if none is saved."""
    mode = _load().get(THEME_KEY)
    return mode if mode in theme.MODES else theme.DEFAULT_MODE


def save_theme(mode: str) -> None:
    """Remember the mode for the next start. Other saved keys are kept."""
    if mode not in theme.MODES:
        raise ValueError(f"Unknown theme mode {mode!r}")
    path = preferences_path()
    data = _load()
    data[THEME_KEY] = mode
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as error:
        log.warning("Could not save preferences to %s: %s", path, error)
