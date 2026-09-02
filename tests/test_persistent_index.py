from sqlalchemy import select


def make_service(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    config = tmp_path / "config"; config.mkdir()
    from app.config import Settings
    from app.service import FileCenterService
    settings = Settings(_env_file=None, CONFIG_DIR=str(config), DATA_MOUNT=str(data), ALLOWED_ROOTS=str(data), QUARANTINE_ROOT=str(data / ".trash"))
    return FileCenterService(settings), data


def test_reindex_root_upserts_and_removes_stale_entries(tmp_path):
    service, data = make_service(tmp_path)
    root = data / "A"; root.mkdir()
    one = root / "one.txt"; one.write_text("1")
    first = service.reindex_root(str(root))
    assert first["files"] == 1

    from app.models import IndexedPath
    with service.SessionLocal() as session:
        rows = list(session.scalars(select(IndexedPath).where(IndexedPath.root_key == str(root.resolve()))))
        assert {r.relative_path for r in rows} == {"one.txt"}
        first_seen = rows[0].first_seen_at

    one.write_text("11")
    two = root / "two.txt"; two.write_text("2")
    service.reindex_root(str(root))
    one.unlink()
    service.reindex_root(str(root))

    with service.SessionLocal() as session:
        rows = list(session.scalars(select(IndexedPath).where(IndexedPath.root_key == str(root.resolve()))))
        assert {r.relative_path for r in rows} == {"two.txt"}
        assert rows[0].first_seen_at >= first_seen


def test_index_match_preview_uses_persisted_roots(tmp_path):
    service, data = make_service(tmp_path)
    a = data / "A"; b = data / "B"; a.mkdir(); b.mkdir()
    (a / "x.jpg").write_text("a"); (b / "x.jpg").write_text("b")
    service.reindex_root(str(a)); service.reindex_root(str(b))
    result = service.index_match_preview([str(a.resolve()), str(b.resolve())], mode="relative-path")
    assert result[0]["key"] == "x.jpg"
    assert len(result[0]["members"]) == 2
