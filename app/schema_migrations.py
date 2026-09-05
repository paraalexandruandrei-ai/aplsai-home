import os
from datetime import datetime, timezone

from sqlalchemy import bindparam, create_engine, inspect, text


MIGRATION_ID = "20260902_01_user_active"
CLIENT_CLASSIFICATION_MIGRATION_ID = "20260905_03_client_classification"
INITIAL_TEST_PURGE_MIGRATION_ID = "20260905_04_purge_confirmed_test_clients"


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


def purge_confirmed_initial_test_clients():
    """Permanently remove only the initial records classified as test data."""
    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS aplsai_schema_migration ("
                "id VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
            ))
            already = conn.execute(
                text("SELECT 1 FROM aplsai_schema_migration WHERE id=:id"),
                {"id": INITIAL_TEST_PURGE_MIGRATION_ID},
            ).first()
            if already:
                return None

            tables = set(inspect(conn).get_table_names())
            client_ids = []
            if "client_profile" in tables:
                columns = {c["name"] for c in inspect(conn).get_columns("client_profile")}
                if "is_test" in columns:
                    client_ids = [row[0] for row in conn.execute(text(
                        "SELECT user_id FROM client_profile WHERE is_test=TRUE"
                    )).all()]

            if client_ids:
                def delete_ids(table, column, values=client_ids):
                    if table not in tables:
                        return
                    statement = text(
                        f'DELETE FROM "{table}" WHERE "{column}" IN :ids'
                    ).bindparams(bindparam("ids", expanding=True))
                    conn.execute(statement, {"ids": values})

                delete_ids("partner_assignment", "client_id")
                delete_ids("client_operation", "client_id")
                delete_ids("deal", "client_id")
                delete_ids("referral", "owner_id")
                delete_ids("document", "client_id")
                delete_ids("update", "client_id")

                if "audit_event" in tables:
                    null_actors = text(
                        "UPDATE audit_event SET actor_user_id=NULL "
                        "WHERE actor_user_id IN :ids"
                    ).bindparams(bindparam("ids", expanding=True))
                    conn.execute(null_actors, {"ids": client_ids})
                    delete_audit = text(
                        "DELETE FROM audit_event WHERE object_type='client' "
                        "AND object_id IN :ids"
                    ).bindparams(bindparam("ids", expanding=True))
                    conn.execute(delete_audit, {"ids": [str(value) for value in client_ids]})

                delete_ids("client_profile", "user_id")
                delete_ids("user", "id")

            conn.execute(
                text(
                    "INSERT INTO aplsai_schema_migration (id, applied_at) "
                    "VALUES (:id, :applied_at)"
                ),
                {
                    "id": INITIAL_TEST_PURGE_MIGRATION_ID,
                    "applied_at": datetime.now(timezone.utc),
                },
            )
        return len(client_ids)
    finally:
        engine.dispose()
