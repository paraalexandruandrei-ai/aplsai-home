import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text


MIGRATION_ID = "20260902_01_user_active"


def _database_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///aplsai.db")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def ensure_user_active_column():
    """Apply the first idempotent schema migration before Flask starts.

    Render currently starts the service directly with gunicorn, without a
    pre-deploy command. This small versioned runner guarantees that the schema
    is upgraded before create_app() queries User. Every applied migration is
    recorded in aplsai_schema_migration and can be inspected later.
    """
    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS aplsai_schema_migration ("
                "id VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
            ))
            already = conn.execute(
                text("SELECT 1 FROM aplsai_schema_migration WHERE id=:id"),
                {"id": MIGRATION_ID},
            ).first()
            if already:
                return False

            inspector = inspect(conn)
            tables = set(inspector.get_table_names())
            if "user" in tables:
                columns = {c["name"] for c in inspector.get_columns("user")}
                if "active" not in columns:
                    conn.execute(text(
                        'ALTER TABLE "user" ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE'
                    ))

            conn.execute(
                text(
                    "INSERT INTO aplsai_schema_migration (id, applied_at) "
                    "VALUES (:id, :applied_at)"
                ),
                {"id": MIGRATION_ID, "applied_at": datetime.now(timezone.utc)},
            )
        return True
    finally:
        engine.dispose()
