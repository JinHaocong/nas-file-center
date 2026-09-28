from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, IndexRoot
from app.organizers.compiler import compile_organizer_preview
from app.workflows.compiler import WorkflowCompiler
from app.workflows.schema import WorkflowDefinition


def _advanced_rules(**overrides):
    rules = {
        "version": 1,
        "directory_depth": {"enabled": False, "rename_from_depth": 2},
        "file_numbering": {
            "enabled": False,
            "start": 1,
            "padding": 3,
            "sort": "natural_name",
            "extension_mode": "preserve",
        },
        "latest_child_prefix": {
            "enabled": False,
            "prefix": "New ",
            "timestamp": "mtime_ns",
        },
        "single_child_wrapper_collapse": {
            "enabled": False,
            "wrapper_depth": 2,
            "child_type": "directory",
        },
    }
    for key, value in overrides.items():
        rules[key].update(value)
    return rules


def _compile(root: Path, rules: dict):
    return compile_organizer_preview(
        root,
        allowed_roots=[root.parent],
        quarantine_root=root.parent / ".trash",
        image_extensions=["jpg", "png"],
        video_extensions=["mp4"],
        rename_template="X-{name}",
        statistics_template="",
        preserve_tags=[],
        cleanup_patterns=[],
        numbering_mode="none",
        numbering_start=1,
        numbering_padding=3,
        mtime_mode="none",
        mtime_delay_seconds=0,
        recursive=True,
        advanced_rules=rules,
    )


def test_depth_rule_preserves_depth1_and_renames_depth2(tmp_path: Path):
    root = tmp_path / "root"
    depth1 = root / "KeepMe"
    depth2 = depth1 / "RenameMe"
    depth2.mkdir(parents=True)

    compilation = _compile(
        root,
        _advanced_rules(directory_depth={"enabled": True, "rename_from_depth": 2}),
    )
    by_source = {proposal.source: proposal for proposal in compilation.proposals}

    assert by_source[str(depth1)].target == str(depth1)
    assert by_source[str(depth1)].changed is False
    assert by_source[str(depth1)].metadata["depth_preserved"] is True
    assert Path(by_source[str(depth2)].target).name == "X-RenameMe"
    assert by_source[str(depth2)].changed is True


def test_file_numbering_resets_per_parent_and_preserves_final_suffix_case(tmp_path: Path):
    root = tmp_path / "root"
    parent_a = root / "A"
    parent_b = root / "A" / "B"
    parent_b.mkdir(parents=True)
    parent_a.mkdir(exist_ok=True)
    for name in ("file10.TXT", "file2.txt", "plain", "z.JPG"):
        (parent_a / name).write_bytes(b"x")
    for name in ("beta.PNG", "alpha"):
        (parent_b / name).write_bytes(b"x")

    compilation = _compile(
        root,
        _advanced_rules(file_numbering={"enabled": True, "start": 1, "padding": 3}),
    )
    rows = [
        proposal
        for proposal in compilation.proposals
        if proposal.proposal_type == "file_rename"
    ]
    targets = {proposal.source: Path(proposal.target).name for proposal in rows}

    assert targets[str(parent_a / "file2.txt")] == "001.txt"
    assert targets[str(parent_a / "file10.TXT")] == "002.TXT"
    assert targets[str(parent_a / "plain")] == "003"
    assert targets[str(parent_a / "z.JPG")] == "004.JPG"
    assert targets[str(parent_b / "alpha")] == "001"
    assert targets[str(parent_b / "beta.PNG")] == "002.PNG"


def test_latest_child_prefix_uses_unique_mtime_and_tie_blocks(tmp_path: Path):
    root = tmp_path / "root"
    parent = root / "A"
    older = parent / "Older"
    newer = parent / "Newer"
    older.mkdir(parents=True)
    newer.mkdir()
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))
    os.utime(newer, ns=(2_000_000_000, 2_000_000_000))

    rules = _advanced_rules(latest_child_prefix={"enabled": True, "prefix": "New "})
    compilation = _compile(root, rules)
    by_source = {proposal.source: proposal for proposal in compilation.proposals}

    assert Path(by_source[str(newer)].target).name == "New X-Newer"
    assert by_source[str(newer)].proposal_type == "latest_child_prefix"
    assert by_source[str(older)].conflict is False

    os.utime(older, ns=(3_000_000_000, 3_000_000_000))
    os.utime(newer, ns=(3_000_000_000, 3_000_000_000))
    tied = _compile(root, rules)
    tied_rows = {
        proposal.source: proposal
        for proposal in tied.proposals
        if proposal.source in {str(older), str(newer)}
    }
    assert tied_rows[str(older)].conflict_reason == "LATEST_CHILD_TIE"
    assert tied_rows[str(newer)].conflict_reason == "LATEST_CHILD_TIE"


def test_wrapper_shape_preview_is_namespace_read_only_and_capability_unverified(tmp_path: Path):
    root = tmp_path / "root"
    child = root / "A" / "Wrapper" / "Child"
    child.mkdir(parents=True)
    before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))

    compilation = _compile(
        root,
        _advanced_rules(single_child_wrapper_collapse={"enabled": True}),
    )
    after = sorted(str(path.relative_to(root)) for path in root.rglob("*"))

    assert before == after
    assert not any(".__probe_" in path for path in after)

    wrappers = [
        proposal
        for proposal in compilation.proposals
        if proposal.proposal_type == "wrapper_collapse"
    ]
    assert len(wrappers) == 1
    assert wrappers[0].source == str(child)
    assert wrappers[0].metadata["capability_state"] == "CAPABILITY_UNVERIFIED"
    assert wrappers[0].metadata["preview_only"] is True
    assert compilation.structural_required is True


def test_advanced_preview_has_digest_but_standalone_plan_persists_zero_draft(tmp_path: Path):
    data = tmp_path / "data"
    root = data / "Organizer"
    (root / "A").mkdir(parents=True)
    (root / "A" / "photo.JPG").write_bytes(b"x")
    config = tmp_path / "config"
    config.mkdir()

    app = create_app(
        Settings(
            config_dir=config,
            data_mount=data,
            allowed_roots_raw=str(data),
            quarantine_root=data / ".trash",
            allow_mutation=True,
            allow_delete=False,
            initial_admin_username="admin",
            initial_admin_password="AdminPassword123!",
        )
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
    ).status_code == 200

    created = client.post(
        "/api/organizer-profiles",
        json={
            "name": "advanced-readonly",
            "root": str(root),
            "recursive": True,
            "advanced_rules": _advanced_rules(file_numbering={"enabled": True}),
        },
    )
    assert created.status_code == 200, created.text
    profile_id = created.json()["id"]

    preview = client.post(f"/api/organizer-profiles/{profile_id}/preview")
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert len(payload["preview_digest"]) == 64
    assert len(payload["source_snapshot_digest"]) == 64
    assert payload["advanced_enabled"] is True
    assert any(row["proposal_type"] == "file_rename" for row in payload["proposals"])

    with app.state.service.SessionLocal() as session:
        before = session.scalar(select(func.count()).select_from(BatchPlan)) or 0

    plan = client.post(f"/api/organizer-profiles/{profile_id}/plan")
    assert plan.status_code == 400
    assert "C1" in plan.json()["detail"]

    with app.state.service.SessionLocal() as session:
        after = session.scalar(select(func.count()).select_from(BatchPlan)) or 0
    assert after == before


def test_workflow_organizer_uses_shared_advanced_preview_compiler(tmp_path: Path):
    data = tmp_path / "data"
    root = data / "Organizer"
    (root / "A").mkdir(parents=True)
    (root / "A" / "image.JPG").write_bytes(b"x")
    config = tmp_path / "config"
    config.mkdir()

    app = create_app(
        Settings(
            config_dir=config,
            data_mount=data,
            allowed_roots_raw=str(data),
            quarantine_root=data / ".trash",
            allow_mutation=False,
            allow_delete=False,
        )
    )

    with app.state.service.SessionLocal() as session:
        index_root = IndexRoot(root=str(root))
        session.add(index_root)
        session.commit()
        session.refresh(index_root)

        definition = WorkflowDefinition.model_validate(
            {
                "schema_version": 1,
                "mode": "organizer",
                "steps": [
                    {"id": "scan", "type": "scan", "root_ids": [index_root.id]},
                    {
                        "id": "organize",
                        "type": "organize",
                        "profile_snapshot": {
                            "name": "advanced-workflow",
                            "recursive": True,
                            "rename_template": "{name}",
                            "statistics_template": "[{files}F]",
                            "advanced_rules": _advanced_rules(
                                file_numbering={"enabled": True}
                            ),
                        },
                    },
                ],
            }
        )
        result = WorkflowCompiler(
            session=session,
            allowed_roots=[data],
            quarantine_root=data / ".trash",
        ).compile(
            definition,
            workflow_id=1,
            workflow_revision=1,
            definition_sha256="a" * 64,
        )

    assert result.compile_context["organizer_advanced_readonly"] is True
    assert len(result.compile_context["organizer_preview_digest"]) == 64
    assert any(
        item.get("proposal_type") == "file_rename"
        for item in result.planned_operations
    )
