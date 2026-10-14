"""Quick health check: lists tables, views, the trigger and the pgvector extension.

Run from the project root:  venv\\Scripts\\python -m scripts.check_db
"""

from sqlalchemy import inspect, text

from app.db import engine
from app.models import Base


def main() -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    expected = set(Base.metadata.tables)

    print(f"Tables ({len(tables)}):")
    for name in sorted(tables):
        print(f"  {'OK ' if name in expected else '   '} {name}")
    missing = expected - tables
    print("Missing tables:", ", ".join(sorted(missing)) if missing else "none")

    print("Views:", ", ".join(sorted(insp.get_view_names())))

    with engine.connect() as conn:
        version = conn.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        trigger = conn.scalar(
            text("SELECT tgname FROM pg_trigger WHERE tgname = 'trg_order_status'")
        )
        revision = conn.scalar(text("SELECT version_num FROM alembic_version"))
    print("pgvector extension:", version or "NOT INSTALLED")
    print("Trigger:", trigger or "NOT FOUND")
    print("Alembic revision:", revision)


if __name__ == "__main__":
    main()
