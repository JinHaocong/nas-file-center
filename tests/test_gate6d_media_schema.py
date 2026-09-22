from pathlib import Path
import sqlite3

from sqlalchemy import delete, inspect, select

from app.db import create_engine_and_session, init_db
from app.models import IndexedPath, MediaAsset, utcnow


def test_gate6d_media_assets_schema_is_additive_and_cascades_with_index(tmp_path: Path):
    db_path = tmp_path / "config" / "app.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path, backups_dir=tmp_path / "backups")

    inspector = inspect(engine)
    assert "media_assets" in inspector.get_table_names()
    columns = {c["name"] for c in inspector.get_columns("media_assets")}
    assert {
        "indexed_path_id",
        "media_kind",
        "width",
        "height",
        "format",
        "date_taken",
        "camera",
        "orientation",
        "duration_seconds",
        "codec",
        "bitrate",
        "fps",
        "audio_codec",
        "integrity_status",
        "integrity_reason_code",
        "integrity_detail",
        "observed_device",
        "observed_inode",
        "observed_size",
        "observed_mtime_ns",
        "corrupt_sha256",
        "verification_sha256",
        "verification_device",
        "verification_inode",
        "verification_size",
        "verification_mtime_ns",
        "verification_status",
        "verification_reason_code",
        "verification_detail",
        "verification_observed_sha256",
        "verification_checked_at",
        "source_scan_generation",
        "probe_generation",
        "probed_at",
        "updated_at",
    }.issubset(columns)

    now = utcnow()
    with SessionLocal() as session:
        path = IndexedPath(
            root_key="/data",
            absolute_path="/data/photo.jpg",
            relative_path="photo.jpg",
            basename="photo.jpg",
            stem="photo",
            suffix=".jpg",
            size=123,
            mtime_ns=456,
            device=11,
            inode=22,
            is_dir=False,
            first_seen_at=now,
            last_seen_at=now,
            scan_generation="scan-a",
        )
        session.add(path)
        session.flush()
        asset = MediaAsset(
            indexed_path_id=path.id,
            media_kind="image",
            integrity_status="unknown",
            observed_device=11,
            observed_inode=22,
            observed_size=123,
            observed_mtime_ns=456,
            source_scan_generation="scan-a",
            probe_generation="probe-a",
            probed_at=now,
            updated_at=now,
        )
        session.add(asset)
        session.commit()
        path_id = path.id
        asset_id = asset.id

    with SessionLocal() as session:
        session.execute(delete(IndexedPath).where(IndexedPath.id == path_id))
        session.commit()

    with SessionLocal() as session:
        assert session.scalar(select(MediaAsset).where(MediaAsset.id == asset_id)) is None



def test_gate6d_integrity_columns_migrate_additively_with_backup(tmp_path: Path):
    db_path = tmp_path / "config" / "app.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE media_assets (
            id INTEGER PRIMARY KEY,
            indexed_path_id INTEGER NOT NULL,
            media_kind VARCHAR(16) NOT NULL,
            width INTEGER,
            height INTEGER,
            format VARCHAR(64),
            date_taken VARCHAR(64),
            camera VARCHAR(255),
            orientation INTEGER,
            duration_seconds FLOAT,
            codec VARCHAR(128),
            bitrate BIGINT,
            fps FLOAT,
            audio_codec VARCHAR(128),
            integrity_status VARCHAR(16) NOT NULL DEFAULT 'unknown',
            integrity_reason_code VARCHAR(128),
            integrity_detail TEXT,
            observed_device BIGINT NOT NULL DEFAULT 0,
            observed_inode BIGINT NOT NULL DEFAULT 0,
            observed_size BIGINT NOT NULL DEFAULT 0,
            observed_mtime_ns BIGINT NOT NULL DEFAULT 0,
            corrupt_sha256 VARCHAR(64),
            source_scan_generation VARCHAR(128) NOT NULL,
            probe_generation VARCHAR(128) NOT NULL,
            probed_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO media_assets (
            id, indexed_path_id, media_kind, integrity_status,
            observed_device, observed_inode, observed_size, observed_mtime_ns,
            source_scan_generation, probe_generation, probed_at, updated_at
        ) VALUES (1, 1, 'image', 'healthy', 1, 2, 3, 4, 'scan-a', 'probe-a',
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    )
    conn.commit()
    conn.close()

    engine, _SessionLocal = create_engine_and_session(db_path)
    backups = tmp_path / "backups"
    init_db(engine, db_path=db_path, backups_dir=backups)

    columns = {c["name"] for c in inspect(engine).get_columns("media_assets")}
    assert {
        "verification_sha256",
        "verification_device",
        "verification_inode",
        "verification_size",
        "verification_mtime_ns",
        "verification_status",
        "verification_reason_code",
        "verification_detail",
        "verification_observed_sha256",
        "verification_checked_at",
    }.issubset(columns)

    with engine.connect() as db:
        status = db.exec_driver_sql(
            "SELECT verification_status FROM media_assets WHERE id = 1"
        ).scalar_one()
    assert status == "unverified"
    assert list(backups.glob("nas-file-center-*.db"))
