from pathlib import Path

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
