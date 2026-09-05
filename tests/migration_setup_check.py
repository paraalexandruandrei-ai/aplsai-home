import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "migration-test-secret"
os.environ.pop("ADMIN_EMAIL", None)
os.environ.pop("ADMIN_PASSWORD", None)

try:
    import manage
    from app.schema_migrations import purge_confirmed_initial_test_clients
    assert manage.app is not None
    assert manage.migrate is not None
    assert manage.app_module.db is not None

    purge_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    purge_tmp.close()
    connection = sqlite3.connect(purge_tmp.name)
    connection.executescript('''
        CREATE TABLE "user" (id INTEGER PRIMARY KEY, role TEXT NOT NULL);
        CREATE TABLE client_profile (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            is_test BOOLEAN NOT NULL DEFAULT FALSE,
            archived_at TIMESTAMP
        );
        INSERT INTO "user" (id, role) VALUES (1, 'client'), (2, 'client'), (3, 'client');
        INSERT INTO client_profile (id, user_id, is_test) VALUES (1, 1, TRUE), (2, 2, TRUE), (3, 3, FALSE);
    ''')
    connection.commit()
    connection.close()
    os.environ["DATABASE_URL"] = f"sqlite:///{purge_tmp.name}"
    assert purge_confirmed_initial_test_clients() == 2
    connection = sqlite3.connect(purge_tmp.name)
    assert connection.execute('SELECT COUNT(*) FROM "user"').fetchone()[0] == 1
    assert connection.execute('SELECT user_id FROM client_profile').fetchone()[0] == 3
    connection.close()
    assert purge_confirmed_initial_test_clients() is None
    os.unlink(purge_tmp.name)
    print("Migration setup OK")
finally:
    try:
        os.unlink(_tmp.name)
    except OSError:
        pass
