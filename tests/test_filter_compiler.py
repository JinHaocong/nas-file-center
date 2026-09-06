import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.models import Base, IndexedPath
from app.filters.schema import LeafNode, LogicalNode
from app.filters.validation import validate_filter_ast
from app.filters.compiler import compile_filter_to_sql

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        # Seed test data
        items = [
            IndexedPath(
                root_key="/data/media",
                absolute_path="/data/media/movie1.mkv",
                relative_path="movies/movie1.mkv",
                basename="movie1.mkv",
                stem="movie1",
                suffix=".mkv",
                size=4 * 1024 * 1024 * 1024,
                mtime_ns=1780000000000000000,
                is_dir=False,
                scan_generation="gen1",
            ),
            IndexedPath(
                root_key="/data/media",
                absolute_path="/data/media/100%_real.txt",
                relative_path="docs/100%_real.txt",
                basename="100%_real.txt",
                stem="100%_real",
                suffix=".txt",
                size=500,
                mtime_ns=1785000000000000000,
                is_dir=False,
                scan_generation="gen1",
            ),
            IndexedPath(
                root_key="/data/media",
                absolute_path="/data/media/1000_real.txt",
                relative_path="docs/1000_real.txt",
                basename="1000_real.txt",
                stem="1000_real",
                suffix=".txt",
                size=600,
                mtime_ns=1786000000000000000,
                is_dir=False,
                scan_generation="gen1",
            ),
            IndexedPath(
                root_key="/data/media",
                absolute_path="/data/media/photo.JPG",
                relative_path="photos/photo.JPG",
                basename="photo.JPG",
                stem="photo",
                suffix=".JPG",
                size=2 * 1024 * 1024,
                mtime_ns=1787000000000000000,
                is_dir=False,
                scan_generation="gen1",
            ),
            IndexedPath(
                root_key="/data/media",
                absolute_path="/data/media/subfolder",
                relative_path="subfolder",
                basename="subfolder",
                stem="subfolder",
                suffix="",
                size=0,
                mtime_ns=1787000000000000000,
                is_dir=True,
                scan_generation="gen1",
            ),
        ]
        session.add_all(items)
        session.commit()
        yield session

def test_literal_wildcard_escaping(db_session: Session):
    # Search for "100%_"
    # Must match "100%_real.txt" but NOT "1000_real.txt"
    leaf = validate_filter_ast(LeafNode(field="name", operator="contains", value="100%_"))
    expr = compile_filter_to_sql(leaf)
    
    stmt = select(IndexedPath.basename).where(IndexedPath.is_dir == False, expr)
    results = db_session.scalars(stmt).all()
    assert results == ["100%_real.txt"]

def test_extension_and_media_type_filter(db_session: Session):
    # Test extension in ["mkv", "jpg"]
    leaf = validate_filter_ast(LeafNode(field="extension", operator="in", value=["mkv", "jpg"]))
    expr = compile_filter_to_sql(leaf)
    stmt = select(IndexedPath.basename).where(IndexedPath.is_dir == False, expr)
    results = set(db_session.scalars(stmt).all())
    assert results == {"movie1.mkv", "photo.JPG"}

    # Test media_type eq "video"
    leaf_v = validate_filter_ast(LeafNode(field="media_type", operator="eq", value="video"))
    expr_v = compile_filter_to_sql(leaf_v)
    stmt_v = select(IndexedPath.basename).where(IndexedPath.is_dir == False, expr_v)
    assert db_session.scalars(stmt_v).all() == ["movie1.mkv"]

def test_size_and_mtime_filter(db_session: Session):
    # Size >= 1GB
    leaf_size = validate_filter_ast(LeafNode(field="size", operator="gte", value=1024*1024*1024))
    stmt = select(IndexedPath.basename).where(IndexedPath.is_dir == False, compile_filter_to_sql(leaf_size))
    assert db_session.scalars(stmt).all() == ["movie1.mkv"]

    # Mtime lt 1785500000000000000
    leaf_mtime = validate_filter_ast(LeafNode(field="mtime", operator="lt", value=1785500000000000000))
    stmt = select(IndexedPath.basename).where(IndexedPath.is_dir == False, compile_filter_to_sql(leaf_mtime))
    results = set(db_session.scalars(stmt).all())
    assert results == {"movie1.mkv", "100%_real.txt"}

def test_composite_logical_filter(db_session: Session):
    tree = LogicalNode(
        op="and",
        children=[
            LeafNode(field="size", operator="lt", value=1000),
            LogicalNode(
                op="not",
                child=LeafNode(field="name", operator="contains", value="%_")
            )
        ]
    )
    validated = validate_filter_ast(tree)
    expr = compile_filter_to_sql(validated)
    stmt = select(IndexedPath.basename).where(IndexedPath.is_dir == False, expr)
    # 1000_real.txt has size 600 (< 1000) and does not contain "%_"
    assert db_session.scalars(stmt).all() == ["1000_real.txt"]
