from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from pathlib import Path
import sqlite3

from sqlalchemy import Engine, create_engine, event, func, inspect, select
from sqlalchemy.orm import sessionmaker

from app.auth.password import hash_password
from app.models import Base, User


@contextmanager
def _db_init_lock(lock_file_path: Path):
    lock_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file_path, "w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def create_engine_and_session(db_path: Path | str):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return engine, SessionLocal


def backup_database(db_path: Path, backups_dir: Path) -> Path | None:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup_file = backups_dir / f"nas-file-center-{ts}.db"

    # Safe SQLite online backup
    src_conn = sqlite3.connect(str(db_path))
    src_conn.execute("PRAGMA busy_timeout=5000")
    dst_conn = sqlite3.connect(str(backup_file))
    with dst_conn:
        src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()
    return backup_file


def init_db(
    engine: Engine,
    db_path: Path | None = None,
    backups_dir: Path | None = None,
    initial_admin_username: str | None = None,
    initial_admin_password: str | None = None,
) -> None:
    # Auto-resolve db_path from engine if not explicitly provided
    if db_path is None and engine.url.database:
        db_path = Path(engine.url.database)

    if backups_dir is None and db_path is not None:
        backups_dir = db_path.parent / "backups"

    lock_file = (db_path.parent / ".db-init.lock") if db_path else Path("/tmp/.nas-file-center-db-init.lock")

    with _db_init_lock(lock_file):
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())

        # If migrating an existing database (has tables) that lacks 'users' table, backup first
        if existing_tables and "users" not in existing_tables:
            if db_path and backups_dir:
                backup_database(db_path, backups_dir)

        # Create all newly defined tables / columns / indexes
        Base.metadata.create_all(engine)

        # Handle initial admin user creation if users table is empty
        if initial_admin_username and initial_admin_password:
            username_clean = initial_admin_username.strip()
            password_clean = initial_admin_password.strip()
            if username_clean and password_clean:
                SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
                with SessionLocal() as session:
                    user_count = session.scalar(select(func.count(User.id))) or 0
                    if user_count == 0:
                        admin_user = User(
                            username=username_clean,
                            password_hash=hash_password(password_clean),
                            role="admin",
                            is_active=True,
                        )
                        session.add(admin_user)
                        session.commit()
