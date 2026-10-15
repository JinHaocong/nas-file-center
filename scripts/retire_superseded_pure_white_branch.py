#!/usr/bin/env python3
"""One-time SHA-pinned retirement of a manually ported Pure White branch.

The original 14-commit design branch has no direct PR head match. Its nine
source files were deliberately carried to current main via merged PR #196.
Never widen the general merged-branch cleaner's exact-PR-head policy.
Dry-run by default; execute only on an approved main push in GitHub Actions.
"""
from __future__ import annotations

import argparse
from urllib.parse import quote

from cleanup_merged_branches import GitHub, credential

REPO = "JinHaocong/nas-file-center"
NAME = "design/pure-white-foundation-shell"
HEAD = "7abdcaddaada997e5f3cddbb6a8486786100223b"
PORT_PR = 196
PORT_PR_HEAD = "8f5a8cf99aff8b13ff290b9906e0a0cee3ab0574"
PORT_MERGE = "29ee9a65d0bbaddb7ec5e48ccbaa1fff8bbc2ec4"
API_ROOT = "/repos/" + REPO


def review(client):
    """Return the exact branch identity only after independent GitHub checks."""
    repo, _ = client.request(API_ROOT)
    if repo.get("archived") or repo.get("default_branch") != "main":
        raise RuntimeError("Repository archived/default branch changed")
    main, _ = client.request(API_ROOT + "/branches/main")
    branch, _ = client.request(API_ROOT + "/branches/" + quote(NAME, safe="/"))
    if branch.get("name") != NAME or branch.get("protected"):
        raise RuntimeError("Design branch protected or renamed")
    if branch.get("commit", {}).get("sha") != HEAD:
        raise RuntimeError("Design branch HEAD changed; refuse retirement")
    if main.get("commit", {}).get("sha") == HEAD:
        raise RuntimeError("Design branch is current main")
    pr, _ = client.request(API_ROOT + "/pulls/" + str(PORT_PR))
    if (not pr.get("merged_at") or
        pr.get("merge_commit_sha") != PORT_MERGE or
        pr.get("head", {}).get("sha") != PORT_PR_HEAD or
        pr.get("head", {}).get("repo", {}).get("full_name") != REPO or
        pr.get("base", {}).get("ref") != "main"):
        raise RuntimeError("Approved port PR #196 identity/merge not verified")
    # The merged port must actually be an ancestor of the live main.
    comparison, _ = client.request(
        API_ROOT + "/compare/" + PORT_MERGE + "..." + main["commit"]["sha"])
    if (comparison.get("status") not in ("ahead", "identical") or
        comparison.get("merge_base_commit", {}).get("sha") != PORT_MERGE):
        raise RuntimeError("Merged port is not an ancestor of current main")
    open_prs = client.paginate(API_ROOT + "/pulls?state=open&per_page=100")
    if any(p.get("head", {}).get("ref") == NAME and
           (p.get("head", {}).get("repo") or {}).get("full_name", "").lower() == REPO.lower()
           for p in open_prs):
        raise RuntimeError("Design branch has an open PR")
    return branch["commit"]["sha"]


def run(client, *, execute=False):
    head = review(client)
    print(f"Verified manually ported Pure White branch {NAME}@{head}; PR #{PORT_PR} merged")
    if not execute:
        print("DRY RUN: no branch removed")
        return False
    # Recheck HEAD/protection and open PRs at the point of deletion.
    if review(client) != head:
        raise RuntimeError("Design branch changed before deletion")
    client.request(API_ROOT + "/git/refs/heads/" + quote(NAME, safe="/"), method="DELETE")
    print(f"DELETED {NAME}@{head}; main unchanged")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Delete the one audited ref")
    args = parser.parse_args()
    run(GitHub(credential()), execute=args.execute)


if __name__ == "__main__":
    main()
