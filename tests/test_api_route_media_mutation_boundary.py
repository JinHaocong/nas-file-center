"""Guard the API router boundary: media-root mutations belong to the Worker.

This is a source-level tripwire, not a substitute for the container read-only
mount acceptance. The dedicated Worker remains the only media-root mutator.
"""
from __future__ import annotations

import ast
from pathlib import Path


ROUTER_FILES = (
    "app/auth/router.py",
    "app/api/router.py",
    "app/api/quarantine_bulk.py",
    "app/media_organizer/router.py",
    "app/download_verification/router.py",
    "app/download_verification/router_sources.py",
    "app/archive_recovery/router.py",
    "app/scheduler/router.py",
)

FORBIDDEN_FILESYSTEM_METHODS = {
    "unlink",
    "remove",
    "rename",
    "replace",
    "rmdir",
    "mkdir",
    "link",
    "symlink",
    "rmtree",
    "move",
    "write_text",
    "write_bytes",
}


def _is_route(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "router"
        ):
            return True
    return False


def _calls(function: ast.FunctionDef | ast.AsyncFunctionDef):
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            yield node


def test_registered_api_routes_do_not_mutate_media_filesystem_directly():
    root = Path(__file__).resolve().parents[1]
    violations: list[str] = []
    route_count = 0

    for relative in ROUTER_FILES:
        source_path = root / relative
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _is_route(node):
                continue
            route_count += 1
            for call in _calls(node):
                method = call.func.attr
                if method in FORBIDDEN_FILESYSTEM_METHODS:
                    violations.append(
                        f"{relative}:{call.lineno} route {node.name} calls "
                        f"filesystem mutation method .{method}()"
                    )

    assert route_count >= 100, f"Router inventory unexpectedly shrank: {route_count} routes"
    assert not violations, "\n".join(violations)


def test_archive_recovery_api_only_enqueues_and_worker_owns_output_creation():
    root = Path(__file__).resolve().parents[1]
    router = (root / "app/archive_recovery/router.py").read_text(encoding="utf-8")
    worker = (root / "app/archive_recovery/integration.py").read_text(encoding="utf-8")

    start = router.split("def start_archive(", 1)[1].split("@router.get('/{job_id}/report')", 1)[0]
    assert "os.mkdir" not in start
    assert ".mkdir(" not in start
    assert ".rmdir(" not in start
    assert "parent_identity" in start
    assert "WorkJob(" in start

    assert "def _create_worker_output_directory(" in worker
    assert "os.mkdir(output.name, mode=0o700, dir_fd=parent_fd)" in worker
    assert "def _persist_worker_output_identity(" in worker
