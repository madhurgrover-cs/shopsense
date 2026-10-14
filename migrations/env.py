"""Alembic environment: connects Alembic to our models and our database URL."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import DATABASE_URL
from app.models import Base  # importing the package registers every table

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate compares the database against this metadata.
target_metadata = Base.metadata

# These views are created with raw SQL in migrations, not by models, so autogenerate
# must not try to drop them.
VIEW_NAMES = {"v_sales_by_category", "v_top_products", "v_daily_revenue", "v_low_stock"}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name in VIEW_NAMES:
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (alembic upgrade head --sql)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply migrations."""
    # NullPool: a migration is a one-off script, no need to keep connections open.
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
