#!/usr/bin/env python3
"""Wait for the current candidate's CI before publishing a candidate-only image."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request

REPOSITORY = "JinHaocong/nas-file-center"
BRANCH = "feature/media-organizer-v16-sdd-foundation"
REQUIRED_WORKFLOWS = (
    ".github/workflows/dependency-audit.yml",
    ".github/workflows/gate6c-tdd.yml",
    ".github/workflows/gate6d-tdd.yml",
    ".github/workflows/organizer-advanced-c5-closure.yml",
    ".github/workflows/media-sort-large-roots.yml",
    ".github/workflows/media_package-preview-regression.yml",
    ".github/workflows/ui-v044-validation.yml",
    ".github/workflows/scheduler-s5-closure.yml",
    ".github/workflows/media-organizer-v16-tdd.yml",
)


class CandidateCIError(RuntimeError):
    """A candidate cannot be published on missing or failed evidence."""


def pending_checks(runs: list[dict], sha: str) -> list[str]:
    latest: dict[str, dict] = {}
    for run in runs:
        path = run.get("path")
        if (path not in REQUIRED_WORKFLOWS or run.get("head_sha") != sha
                or run.get("event") != "pull_request" or run.get("head_branch") != BRANCH):
            continue
        if path not in latest or int(run["id"]) > int(latest[path]["id"]):
            latest[path] = run
    pending = []
    for path in REQUIRED_WORKFLOWS:
        run = latest.get(path)
        if run is None or run.get("status") != "completed":
            pending.append(path)
        elif run.get("conclusion") != "success":
            raise CandidateCIError(f"{path}: {run.get('conclusion')} (run {run['id']})")
    return pending


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=2100)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        raise CandidateCIError("A full candidate commit SHA is required")
    if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or os.environ.get("GITHUB_REF") != f"refs/heads/{BRANCH}"
            or os.environ.get("GITHUB_SHA") != args.sha):
        raise CandidateCIError("Untrusted repository, branch or workflow SHA")
    token = os.environ.get("GITHUB_TOKEN")
    if not token or not 1 <= args.timeout_seconds <= 3600:
        raise CandidateCIError("Missing Actions token or invalid timeout")
    query = urllib.parse.urlencode({"head_sha": args.sha, "event": "pull_request", "per_page": 100})
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/actions/runs?{query}",
        headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "nfc-v16-candidate-ci"},
    )
    deadline = time.monotonic() + args.timeout_seconds
    while True:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        pending = pending_checks(payload["workflow_runs"], args.sha)
        if not pending:
            print(f"CANDIDATE_CI_PASSED sha={args.sha} workflows={len(REQUIRED_WORKFLOWS)}", flush=True)
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CandidateCIError("Timed out waiting for: " + ", ".join(pending))
        print("Waiting for candidate CI: " + ", ".join(pending), flush=True)
        time.sleep(min(20, remaining))


if __name__ == "__main__":
    main()
