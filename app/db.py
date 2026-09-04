from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sqlite3

from sqlalchemy import Engine, create_engine, delete, event, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app.auth.password import hash_password
from app.models import Base, IndexRoot, IndexedPath, OrganizerProfile, User, WorkJob


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

        required_tables = {
            "users",
            "sessions",
            "favorite_paths",
            "recent_paths",
            "organizer_profiles",
            "worker_state",
            "task_events",
            "index_roots",
        }

        # Check existing columns in work_jobs
        missing_work_job_cols: list[tuple[str, str]] = []
        if "work_jobs" in existing_tables:
            current_cols = {c["name"] for c in inspector.get_columns("work_jobs")}
            expected_new_cols = [
                ("progress_message", "TEXT"),
                ("checkpoint_json", "TEXT DEFAULT '{}'"),
                ("error_code", "VARCHAR(64)"),
                ("pause_requested_at", "DATETIME"),
                ("cancel_requested_at", "DATETIME"),
                ("heartbeat_at", "DATETIME"),
                ("retry_of", "INTEGER REFERENCES work_jobs(id) ON DELETE SET NULL"),
            ]
            missing_work_job_cols = [(col, ctype) for col, ctype in expected_new_cols if col not in current_cols]

        needs_backup = bool(
            existing_tables
            and (
                not required_tables.issubset(existing_tables)
                or bool(missing_work_job_cols)
            )
        )
        if needs_backup and db_path and backups_dir:
            backup_database(db_path, backups_dir)

        # Migrate missing columns into work_jobs if needed
        if missing_work_job_cols:
            with engine.connect() as conn:
                for col, ctype in missing_work_job_cols:
                    conn.execute(text(f"ALTER TABLE work_jobs ADD COLUMN {col} {ctype}"))
                conn.commit()

        # Create all newly defined tables / columns / indexes
        Base.metadata.create_all(engine)

        # Ensure performance indexes exist on work_jobs
        with engine.connect() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_work_jobs_retry_of ON work_jobs(retry_of)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_work_jobs_created_at ON work_jobs(created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_work_jobs_heartbeat_at ON work_jobs(heartbeat_at)"))
            conn.commit()

        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

        # Backfill index_roots from existing indexed_paths and active index-root work_jobs
        with SessionLocal() as session:
            session.execute(
                text("""
                    INSERT OR IGNORE INTO index_roots (root, created_at, last_indexed_at)
                    SELECT 
                        root_key AS root,
                        COALESCE(MIN(first_seen_at), CURRENT_TIMESTAMP) AS created_at,
                        MAX(last_seen_at) AS last_indexed_at
                    FROM indexed_paths
                    WHERE root_key IS NOT NULL AND TRIM(root_key) != ''
                    GROUP BY root_key
                """)
            )

            # Backfill from active index-root work_jobs (status not terminal)
            active_jobs = session.execute(
                select(WorkJob.created_at, WorkJob.state_json)
                .where(
                    WorkJob.kind == "index-root",
                    WorkJob.status.not_in(["completed", "failed", "cancelled"]),
                )
            ).all()

            for job_created_at, state_json in active_jobs:
                if not state_json:
                    continue
                try:
                    payload = json.loads(state_json)
                    root_val = payload.get("root")
                    if root_val and isinstance(root_val, str) and root_val.strip():
                        root_clean = root_val.strip()
                        session.execute(
                            text("""
                                INSERT OR IGNORE INTO index_roots (root, created_at, last_indexed_at)
                                VALUES (:root, :created_at, NULL)
                            """),
                            {"root": root_clean, "created_at": job_created_at or datetime.now(timezone.utc)},
                        )
                except Exception:
                    pass

            session.commit()

        # Ensure no builtin profiles exist; organizer profiles count starts at 0
        with SessionLocal() as session:
            session.execute(
                delete(OrganizerProfile).where(
                    OrganizerProfile.is_builtin == True,
                )
            )
            session.commit()

        # Handle initial admin user creation if users table is empty
        if initial_admin_username and initial_admin_password:
            username_clean = initial_admin_username.strip()
            password_clean = initial_admin_password.strip()
            if username_clean and password_clean:
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
