from sqlalchemy import select


def test_zfs_unsigned_inode_round_trips_without_sqlite_overflow(tmp_path):
    from app.db import create_engine_and_session, init_db
    from app.models import IndexedPath

    engine, SessionLocal = create_engine_and_session(tmp_path / "app.db")
    init_db(engine)
    huge_inode = 12164156718799206349

    with SessionLocal() as session:
        session.add(IndexedPath(
            root_key="/data/A",
            absolute_path="/data/A/重复文件1.bin",
            relative_path="重复文件1.bin",
            basename="重复文件1.bin",
            stem="重复文件1",
            suffix=".bin",
            size=1048576,
            mtime_ns=1,
            device=74,
            inode=huge_inode,
            is_dir=False,
            scan_generation="zfs-test",
        ))
        session.commit()

    with SessionLocal() as session:
        row = session.scalar(select(IndexedPath))
        assert row is not None
        assert row.device == 74
        assert row.inode == huge_inode
        assert isinstance(row.inode, int)


def test_zfs_unsigned_inode_is_safe_with_legacy_integer_affinity_column(tmp_path):
    import sqlite3

    from sqlalchemy import bindparam, create_engine, literal_column, select, text

    from app.dbtypes import FilesystemId

    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE legacy_paths (id INTEGER PRIMARY KEY, inode INTEGER)")
    connection.commit()
    connection.close()

    engine = create_engine(f"sqlite:///{database}")
    huge_inode = 12164156718799206349

    with engine.begin() as connection:
        statement = text("INSERT INTO legacy_paths(inode) VALUES (:inode)").bindparams(
            bindparam("inode", type_=FilesystemId())
        )
        connection.execute(statement, {"inode": huge_inode})

    with engine.connect() as connection:
        decoded = connection.execute(
            select(literal_column("inode", type_=FilesystemId())).select_from(text("legacy_paths"))
        ).scalar_one()
        storage_type = connection.execute(text("SELECT typeof(inode) FROM legacy_paths")).scalar_one()

    assert decoded == huge_inode
    assert storage_type == "text"
