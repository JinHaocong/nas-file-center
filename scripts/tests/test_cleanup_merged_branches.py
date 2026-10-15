#!/usr/bin/env python3
"""Offline unit tests for branch-cleaner safety decisions. No GitHub writes."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

tool = Path(__file__).resolve().parents[1] / "cleanup_merged_branches.py"
spec = importlib.util.spec_from_file_location("cleanup_merged_branches", tool)
cleaner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleaner)
REPO = "JinHaocong/nas-file-center"
OLD = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
RECENT = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
FUTURE = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def branch(name="feat/old", sha="abc", protected=False):
    return {"name": name, "commit": {"sha": sha}, "protected": protected}


def pull(name="feat/old", sha="abc", state="closed", merged_at=OLD, base="main"):
    return {"number": 7, "state": state, "merged_at": merged_at,
            "head": {"ref": name, "sha": sha, "repo": {"full_name": REPO}},
            "base": {"ref": base}}


def choice(b=None, ps=None, days=cleaner.DEFAULT_MIN_AGE_DAYS, prefix=""):
    return cleaner.eligible(b or branch(), [pull()] if ps is None else ps, REPO,
                            "main", datetime.now(timezone.utc) - timedelta(days=days),
                            prefix)[0]


class BranchCleanupSafety(unittest.TestCase):
    def test_merged_exact_sha_is_candidate(self):
        self.assertTrue(choice())

    def test_default_immediate_cleanup_and_optional_retention(self):
        self.assertEqual(cleaner.build_parser().parse_args(["--repo", REPO]).min_age_days, 0)
        self.assertFalse(cleaner.build_parser().parse_args(["--repo", REPO]).execute,
                         "must remain dry-run unless --execute is explicitly requested")
        self.assertTrue(cleaner.build_parser().parse_args(
            ["--repo", REPO, "--execute"]).execute)
        self.assertTrue(choice(ps=[pull(merged_at=RECENT)]),
                        "a freshly merged exact-SHA branch is eligible")
        self.assertFalse(choice(ps=[pull(merged_at=RECENT)], days=7),
                         "the user may still request a seven-day hold")
        self.assertFalse(choice(ps=[pull(merged_at=FUTURE)]),
                         "future merge timestamps must fail closed")

    def test_protected_and_reserved_branches_never_delete(self):
        self.assertFalse(choice(branch(protected=True)))
        for name in ("main", "master", "develop", "release/1.0", "hotfix/urgent"):
            self.assertFalse(choice(branch(name=name), [pull(name=name)]))

    def test_open_or_unmerged_pr_never_delete(self):
        self.assertFalse(choice(ps=[pull(state="open", merged_at=None)]))
        self.assertFalse(choice(ps=[pull(merged_at=None)]))
        self.assertFalse(choice(ps=[pull(), pull(state="closed", merged_at=None)]))

    def test_sha_base_repo_and_age_must_match(self):
        self.assertFalse(choice(b=branch(sha="new")))
        self.assertFalse(choice(ps=[pull(base="develop")]))
        self.assertFalse(choice(ps=[pull(merged_at=FUTURE)]))
        other = pull()
        other["head"]["repo"]["full_name"] = "someone/else"
        self.assertFalse(choice(ps=[other]))

    def test_prefix_restricts_candidates(self):
        self.assertFalse(choice(prefix="chore/"))
        self.assertTrue(choice(prefix="feat/"))


    def test_actions_cleanup_is_only_post_merge_main_push_with_scoped_token(self):
        workflow = (Path(__file__).resolve().parents[2]
                    / ".github/workflows/merged-branch-cleanup.yml").read_text()
        for token in [
            "name: Merged Branch Cleanup", "branches: [main]",
            "workflow_dispatch:", "contents: write",
            "github.repository == 'JinHaocong/nas-file-center'",
            "github.ref == 'refs/heads/main'",
            "persist-credentials: false",
            "python3 scripts/cleanup_merged_branches.py --repo JinHaocong/nas-file-center",
            "--execute", "GH_TOKEN: ${{ github.token }}",
            "cancel-in-progress: false",
        ]:
            self.assertIn(token, workflow, token)
        self.assertNotIn("pull_request:", workflow,
                         "cleanup must not delete an active PR branch")


if __name__ == "__main__":
    unittest.main()
