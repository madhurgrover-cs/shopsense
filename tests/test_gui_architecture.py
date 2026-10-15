"""Enforce the architecture rule: GUI code only talks to services.

Reads every GUI source file (without running it) and fails if it imports SQLAlchemy,
the database module, models, repositories or the AI package directly.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUI_FILES = sorted((ROOT / "app" / "gui").rglob("*.py")) + [ROOT / "main.py"]
FORBIDDEN = ("sqlalchemy", "app.db", "app.models", "app.repositories", "app.ai")


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            # "from app import db" imports app.db too
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_gui_files_were_found():
    assert len(GUI_FILES) > 5


@pytest.mark.parametrize("path", GUI_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_gui_only_imports_services(path):
    bad = sorted(m for m in imported_modules(path)
                 if any(m == f or m.startswith(f + ".") for f in FORBIDDEN))
    assert not bad, f"{path.name} imports {bad}; the GUI must go through app.services"
