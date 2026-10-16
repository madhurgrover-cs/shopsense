"""Application configuration, loaded from the .env file in the project root.

Every other module reads settings from here instead of calling os.getenv directly,
so there is exactly one place that knows where configuration comes from.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = the folder that contains this "app" package.
BASE_DIR = Path(__file__).resolve().parent.parent

# override=False: a real environment variable (e.g. set in CI) wins over the .env file.
load_dotenv(BASE_DIR / ".env", override=False)


def _require(name: str) -> str:
    """Return an environment variable or fail with a clear message."""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


def _normalise_db_url(url: str) -> str:
    """Make sure SQLAlchemy uses the psycopg 3 driver.

    Neon's dashboard gives URLs starting with "postgresql://" (or "postgres://").
    Without an explicit driver SQLAlchemy would look for psycopg2, which we don't install.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL: str = _normalise_db_url(_require("DATABASE_URL"))
SQL_ECHO: bool = os.getenv("SQL_ECHO", "0") == "1"

# "Ask your data" (admin screen) sends questions to Google Gemini. The key is optional:
# without it the app works normally and that one screen explains how to add it.
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
# Current models available on the free tier. Change them in .env if Google retires one
# (the screen then says the model isn't available). The free tier is sometimes
# overloaded ("503 high demand"); the request is then sent to the fallback model.
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "").strip() or "gemini-3.5-flash"
GEMINI_FALLBACK_MODEL: str = (os.getenv("GEMINI_FALLBACK_MODEL", "").strip()
                              or "gemini-3.5-flash-lite")
