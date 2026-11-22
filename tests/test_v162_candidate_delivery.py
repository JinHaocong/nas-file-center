"""V1.6.2 candidate publication is immutable, gated, and pull-only on the NAS."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "feat/v1.6.2-nas-compat-feasibility"
REPOSITORY = "JinHaocong/nas-file-center"


def test_nas_acceptance_script_pulls_digest_and_never_builds_locally():
    script = (ROOT / "scripts/v162_run_disposable_nas_acceptance.sh").read_text()
    assert "--image-ref" in script
    assert "kerwinjhc/nas-file-center@sha256:" in script
    assert 'docker pull "$IMAGE_REF"' in script
    assert 'docker build ' not in script
    assert "org.opencontainers.image.revision" in script
    assert "docker image inspect --format" in script
    assert "--nas-root-worker" in script


def test_candidate_workflow_is_gated_to_exact_branch_and_commit_marker():
    workflow = yaml.safe_load((ROOT / ".github/workflows/v162-candidate-publish.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["push"]["branches"] == [BRANCH]
    job = workflow["jobs"]["candidate"]
    condition = job["if"]
    assert REPOSITORY in condition
    assert f"refs/heads/{BRANCH}" in condition
    assert "[publish-v162-candidate]" in condition


def test_candidate_tag_is_unique_and_never_overwrites_release_aliases():
    workflow = (ROOT / ".github/workflows/v162-candidate-publish.yml").read_text()
    assert "v1.6.2-nas-compat-$SHORT" in workflow
    assert "push: false" in workflow
    assert 'docker push "$CANDIDATE_IMAGE"' in workflow
    assert "kerwinjhc/nas-file-center:latest" not in workflow
    assert "nas-file-center:1.6.2" not in workflow


def test_candidate_requires_full_lifecycle_before_registry_push():
    workflow = (ROOT / ".github/workflows/v162-candidate-publish.yml").read_text()
    lifecycle = workflow.index("Full Root Worker lifecycle on disposable GitHub runner filesystem")
    push = workflow.index("Push only the unique candidate tag and resolve immutable digest")
    assert lifecycle < push
    assert "--nas-root-worker" in workflow
    assert "PASS_MAINTENANCE_LIFECYCLE" in workflow
    assert "release_ready" in workflow

