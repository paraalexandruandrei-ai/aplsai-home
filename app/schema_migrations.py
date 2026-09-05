import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text


MIGRATION_ID = "20260902_01_user_active"
CLIENT_CLASSIFICATION_MIGRATION_ID = "20260905_03_client_classification"


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


def ensure_client_classification_columns():
    """Add non-destructive real/test and archive state to client profiles.

    The records already present when this migration first runs are the two
    founder-created trial profiles confirmed as test data. Future profiles are
    real by default and can be reclassified by an Admin.
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
                {"id": CLIENT_CLASSIFICATION_MIGRATION_ID},
            ).first()
            if already:
                return False

            inspector = inspect(conn)
            tables = set(inspector.get_table_names())
            if "client_profile" in tables:
                columns = {c["name"] for c in inspector.get_columns("client_profile")}
                if "is_test" not in columns:
                    conn.execute(text(
                        "ALTER TABLE client_profile ADD COLUMN is_test "
                        "BOOLEAN NOT NULL DEFAULT FALSE"
                    ))
                if "archived_at" not in columns:
                    conn.execute(text(
                        "ALTER TABLE client_profile ADD COLUMN archived_at TIMESTAMP"
                    ))
                conn.execute(text("UPDATE client_profile SET is_test=TRUE"))

            conn.execute(
                text(
                    "INSERT INTO aplsai_schema_migration (id, applied_at) "
                    "VALUES (:id, :applied_at)"
                ),
                {
                    "id": CLIENT_CLASSIFICATION_MIGRATION_ID,
                    "applied_at": datetime.now(timezone.utc),
                },
            )
        return True
    finally:
        engine.dispose()
