"""Candidate delivery must not overwrite a release or build on the NAS."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "feature/media-organizer-v16-sdd-foundation"
REPOSITORY = "JinHaocong/nas-file-center"


def _workflow():
    return yaml.safe_load((ROOT / ".github/workflows/dockerhub-publish.yml").read_text())


def _candidate_job():
    jobs = _workflow()["jobs"]
    assert "candidate-publish" in jobs, "GitHub must publish the candidate without a NAS build"
    return jobs["candidate-publish"]


def test_fresh_install_pulls_the_published_image_without_host_ports():
    model = yaml.safe_load((ROOT / "compose.komodo.v16-fresh-install.yaml").read_text())
    for service in model["services"].values():
        assert "build" not in service, "Komodo must pull the tested registry image"
        assert service["pull_policy"] == "missing"
        assert not service.get("ports"), "Initial bootstrap publishes no host ports"
        data = next(v for v in service["volumes"] if isinstance(v, dict) and v["target"] == "/data")
        assert data["read_only"] is True
        assert service["environment"]["MEDIA_ORGANIZER_EXECUTION_ENABLED"] == "false"


def test_candidate_trigger_and_release_job_remain_separate():
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    assert BRANCH in triggers["push"]["branches"]
    assert "pull_request_target" not in triggers
    assert "refs/heads/main" in workflow["jobs"]["publish"]["if"]
    job = _candidate_job()
    assert REPOSITORY in job["if"] and f"refs/heads/{BRANCH}" in job["if"]
    step_names = [step.get("id") for step in job["steps"]]
    assert step_names.index("smoke") < step_names.index("push")
    assert step_names.index("ci") < step_names.index("push")


@pytest.mark.parametrize("override,expected_success", [
    ({}, True),
    ({"GITHUB_REF": "refs/heads/main"}, False),
    ({"GITHUB_REPOSITORY": "unrelated/project"}, False),
    ({"GITHUB_SHA": "a" * 40}, False),
    ({"GITHUB_SHA": "a" * 7}, False),
])
def test_candidate_identity_uses_full_current_sha_and_no_release_alias(tmp_path, override, expected_success):
    job = _candidate_job()
    identity = next(step for step in job["steps"] if step.get("id") == "identity")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    output = tmp_path / "output"
    env = {**os.environ, "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_REF": f"refs/heads/{BRANCH}",
           "GITHUB_SHA": sha, "GITHUB_OUTPUT": str(output), **override}
    result = subprocess.run(["bash", "-c", identity["run"]], cwd=ROOT, env=env, capture_output=True, text=True)
    assert (result.returncode == 0) is expected_success, result.stderr
    if expected_success:
        assert output.read_text().splitlines() == [f"tag=kerwinjhc/nas-file-center:v1.6-candidate-{sha}"]
    else:
        assert not output.exists() or not output.read_text()


def _passed_runs(gate, sha="a" * 40):
    return [{"id": number, "path": path, "head_sha": sha, "event": "pull_request",
             "head_branch": BRANCH, "status": "completed", "conclusion": "success"}
            for number, path in enumerate(gate.REQUIRED_WORKFLOWS, 1)]


def test_ci_gate_requires_all_exact_commit_workflows():
    from scripts import verify_v16_candidate_ci as gate
    runs = _passed_runs(gate)
    assert gate.pending_checks(runs, "a" * 40) == []
    assert gate.pending_checks(runs, "b" * 40)
    assert gate.pending_checks(runs[:-1], "a" * 40)
    for row in runs:
        row["event"] = "push"
    assert gate.pending_checks(runs, "a" * 40)


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", "timed_out"])
def test_ci_gate_refuses_newer_nonpassing_attempt_even_after_old_success(conclusion):
    from scripts import verify_v16_candidate_ci as gate
    runs = _passed_runs(gate)
    failed = {**runs[0], "id": 100, "conclusion": conclusion}
    with pytest.raises(gate.CandidateCIError):
        gate.pending_checks([failed, *runs], "a" * 40)


def test_ci_gate_waits_for_running_latest_attempt():
    from scripts import verify_v16_candidate_ci as gate
    runs = _passed_runs(gate)
    later = {**runs[0], "id": 100, "status": "in_progress", "conclusion": None}
    assert gate.pending_checks([*runs, later], "a" * 40) == [later["path"]]


def test_ci_gate_does_not_mutate_evidence():
    from scripts import verify_v16_candidate_ci as gate
    runs = _passed_runs(gate)
    before = copy.deepcopy(runs)
    gate.pending_checks(runs, "a" * 40)
    assert runs == before
