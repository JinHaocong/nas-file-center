from contextlib import contextmanager
import fcntl
import importlib
import os
import selectors
import subprocess
import sys
import threading
from time import monotonic

import pytest

from app.config import Settings


LOCK_NAME = ".media-mutation.lock"


@pytest.fixture
def config(tmp_path):
    return Settings(config_dir=tmp_path)


def _lock_module():
    return importlib.import_module("app.tasks.media_mutation_lock")


def _read_line(process, timeout=4):
    fd = process.stdout.fileno()
    deadline = monotonic() + timeout
    line = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_READ)
        while selector.select(max(0, deadline - monotonic())):
            byte = os.read(fd, 1)
            if not byte or byte == b"\n":
                return line.decode()
            line.extend(byte)
    return None


@contextmanager
def _process(script, config):
    with subprocess.Popen(
        [sys.executable, "-c", script, str(config.config_dir)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    ) as process:
        try:
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=4)


@contextmanager
def external_holder(config):
    script = """
import fcntl, pathlib, sys
path = pathlib.Path(sys.argv[1]) / ".media-mutation.lock"
with path.open("a") as lock:
    path.chmod(0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    print("held", flush=True)
    sys.stdin.readline()
"""
    with _process(script, config) as holder:
        assert _read_line(holder) == "held"
        yield holder


def test_subprocess_holder_survives_expired_database_lease(config):
    from datetime import timedelta
    from app.db import create_engine_and_session, init_db
    from app.models import TaskLock, utcnow
    from app.tasks.recovery import acquire_worker_ownership

    engine, sessions = create_engine_and_session(config.database_path)
    init_db(engine, db_path=config.database_path)
    assert acquire_worker_ownership(engine, sessions, worker_id="old")

    holder_script = """
import sys
from app.config import Settings
from app.tasks.media_mutation_lock import media_mutation_lock
with media_mutation_lock(Settings(config_dir=sys.argv[1])):
    print("held", flush=True)
    sys.stdin.readline()
"""
    contender_script = """
import sys
from app.config import Settings
from app.tasks.media_mutation_lock import media_mutation_lock
print("waiting", flush=True)
with media_mutation_lock(Settings(config_dir=sys.argv[1])):
    print("acquired", flush=True)
"""
    with _process(holder_script, config) as holder:
        assert _read_line(holder) == "held"
        with sessions.begin() as session:
            session.get(TaskLock, 1).acquired_at = utcnow() - timedelta(minutes=2)
        assert acquire_worker_ownership(engine, sessions, worker_id="new")
        with _process(contender_script, config) as contender:
            assert _read_line(contender) == "waiting"
            assert _read_line(contender, timeout=0.2) is None
            holder.stdin.write("\n")
            holder.stdin.flush()
            assert _read_line(contender) == "acquired"
            assert contender.wait(timeout=4) == 0


def test_reentrant_holder_excludes_other_threads_and_releases_on_exception(config):
    lock_module = _lock_module()
    entered = threading.Event()

    def contender():
        with lock_module.media_mutation_lock(config):
            entered.set()

    with pytest.raises(RuntimeError, match="unwind"):
        with lock_module.media_mutation_lock(config):
            with lock_module.media_mutation_lock(config):
                lock_module.assert_media_mutation_lock(config)
            thread = threading.Thread(target=contender, daemon=True)
            thread.start()
            assert not entered.wait(timeout=0.2)
            raise RuntimeError("unwind")
    assert entered.wait(timeout=4)
    thread.join(timeout=4)


def test_refuses_lock_symlink_and_unsafe_permissions(config):
    lock_module = _lock_module()
    lock_path = config.config_dir / LOCK_NAME
    target = config.config_dir / "other"
    target.write_text("untouched")
    lock_path.symlink_to(target)
    with pytest.raises(PermissionError):
        with lock_module.media_mutation_lock(config):
            pytest.fail("followed a lock symlink")
    assert target.read_text() == "untouched"
    lock_path.unlink()
    lock_path.touch(mode=0o666)
    lock_path.chmod(0o666)
    with pytest.raises(PermissionError):
        with lock_module.media_mutation_lock(config):
            pytest.fail("accepted a writable public lock")


def test_existing_lock_open_uses_pinned_proc_fd_when_zfuse_openat_returns_enoent(config, monkeypatch):
    lock_module = _lock_module()
    lock_path = config.config_dir / LOCK_NAME
    lock_path.write_text("")
    lock_path.chmod(0o600)
    original_open = os.open

    def zfuse_open(path, flags, *args, **kwargs):
        if os.fspath(path) == LOCK_NAME and kwargs.get("dir_fd") is not None:
            raise FileNotFoundError(2, "simulated zfuse openat lookup failure", os.fspath(path))
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(lock_module.os, "open", zfuse_open)
    with lock_module.media_mutation_lock(config):
        lock_module.assert_media_mutation_lock(config)


def test_config_path_cannot_hide_a_symlink_with_parent_traversal(config):
    lock_module = _lock_module()
    root = config.config_dir
    (root / "alternate" / "child").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "alternate" / "config").mkdir()
    (root / "redirect").symlink_to(root / "alternate" / "child", target_is_directory=True)
    settings = Settings(config_dir=root / "redirect" / ".." / "config")
    with pytest.raises(PermissionError):
        with lock_module.media_mutation_lock(settings):
            pytest.fail("locked a different config directory than the OS path resolves to")


def test_replacement_does_not_open_second_lock(config):
    lock_module = _lock_module()
    lock_path = config.config_dir / LOCK_NAME
    with pytest.raises(PermissionError):
        with lock_module.media_mutation_lock(config):
            lock_path.rename(config.config_dir / "old-lock")
            lock_path.touch(mode=0o600)
            with pytest.raises(PermissionError):
                lock_module.assert_media_mutation_lock(config)
    with pytest.raises(PermissionError):
        with lock_module.media_mutation_lock(config):
            pytest.fail("accepted a changed lock inode")


def test_fork_neither_inherits_authority_nor_keeps_parent_flock_alive(config):
    script = """
import os, sys
from app.config import Settings
from app.tasks.media_mutation_lock import assert_media_mutation_lock, media_mutation_lock
settings = Settings(config_dir=sys.argv[1])
with media_mutation_lock(settings):
    child = os.fork()
    if child == 0:
        try:
            assert_media_mutation_lock(settings)
        except PermissionError:
            print("no inherited authority", flush=True)
        else:
            os._exit(2)
        sys.stdin.readline()
        os._exit(0)
print("parent released", flush=True)
_, status = os.waitpid(child, 0)
sys.exit(os.waitstatus_to_exitcode(status))
"""
    with _process(script, config) as parent:
        lines = {_read_line(parent), _read_line(parent)}
        assert lines == {"no inherited authority", "parent released"}
        with (config.config_dir / LOCK_NAME).open("r+") as contender:
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        parent.stdin.write("\n")
        parent.stdin.flush()
        assert parent.wait(timeout=4) == 0
