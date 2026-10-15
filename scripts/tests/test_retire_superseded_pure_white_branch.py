#!/usr/bin/env python3
"""Offline fail-closed tests for the one-time, exact-SHA design ref retirement."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import retire_superseded_pure_white_branch as retire


class FakeGitHub:
    def __init__(self):
        self.repo = {"default_branch": "main", "archived": False}
        self.main = {"commit": {"sha": "9271d1430fc4e6833ed1447f2abefa0af63807d1"}}
        self.branch = {"name": retire.NAME, "protected": False,
                       "commit": {"sha": retire.HEAD}}
        self.pr = {"merged_at": "2026-10-13T08:00:00Z",
                   "merge_commit_sha": retire.PORT_MERGE,
                   "head": {"sha": retire.PORT_PR_HEAD, "repo": {"full_name": retire.REPO}},
                   "base": {"ref": "main"}}
        self.compare = {"status": "ahead",
                        "merge_base_commit": {"sha": retire.PORT_MERGE}}
        self.open_prs = []
        self.deletes = []
        self.branch_reads = 0

    def request(self, path, method="GET"):
        if method == "DELETE":
            self.deletes.append(path)
            return None, ""
        if path == retire.API_ROOT:
            return self.repo, ""
        if path == retire.API_ROOT + "/branches/main":
            return self.main, ""
        if path == retire.API_ROOT + "/branches/" + retire.NAME:
            self.branch_reads += 1
            return self.branch, ""
        if path == retire.API_ROOT + "/pulls/196":
            return self.pr, ""
        if path.startswith(retire.API_ROOT + "/compare/"):
            return self.compare, ""
        raise AssertionError(f"Unexpected REST request {method} {path}")

    def paginate(self, path):
        if path != retire.API_ROOT + "/pulls?state=open&per_page=100":
            raise AssertionError(path)
        return self.open_prs


class RetirementSafety(unittest.TestCase):
    def test_dry_run_even_when_eligible(self):
        api = FakeGitHub()
        self.assertFalse(retire.run(api))
        self.assertEqual(api.deletes, [])

    def test_only_exact_verified_design_ref_can_be_deleted(self):
        api = FakeGitHub()
        self.assertTrue(retire.run(api, execute=True))
        self.assertEqual(api.deletes, [
            retire.API_ROOT + "/git/refs/heads/design/pure-white-foundation-shell"])
        self.assertGreaterEqual(api.branch_reads, 2)

    def test_all_identity_guards_fail_closed(self):
        for key, edit in [
            ("protected", lambda a: a.branch.update(protected=True)),
            ("head", lambda a: a.branch["commit"].update(sha="different")),
            ("branch", lambda a: a.branch.update(name="main")),
            ("archived", lambda a: a.repo.update(archived=True)),
            ("default", lambda a: a.repo.update(default_branch="develop")),
            ("merged_at", lambda a: a.pr.update(merged_at=None)),
            ("merge_sha", lambda a: a.pr.update(merge_commit_sha="wrong")),
            ("pr_head", lambda a: a.pr["head"].update(sha="wrong")),
            ("pr_repo", lambda a: a.pr["head"]["repo"].update(full_name="other/repo")),
            ("base", lambda a: a.pr["base"].update(ref="develop")),
            ("ancestry", lambda a: a.compare["merge_base_commit"].update(sha="wrong")),
            ("history", lambda a: a.compare.update(status="diverged")),
            ("open_pr", lambda a: a.open_prs.append({
                "head": {"ref": retire.NAME, "repo": {"full_name": retire.REPO}}})),
        ]:
            with self.subTest(case=key):
                api = FakeGitHub()
                edit(api)
                with self.assertRaises(RuntimeError):
                    retire.run(api, execute=True)
                self.assertEqual(api.deletes, [])

    def test_idempotent_after_ref_is_gone(self):
        api = FakeGitHub()
        orig = api.request
        def no_branch(path, method="GET"):
            if path == retire.API_ROOT + "/branches/" + retire.NAME:
                raise RuntimeError("GitHub GET failed (404): Not Found")
            return orig(path, method)
        api.request = no_branch
        self.assertFalse(retire.run(api, execute=True))
        self.assertEqual(api.deletes, [])

    def test_second_review_prevents_head_race(self):
        api = FakeGitHub()
        orig = api.request
        def changing(path, method="GET"):
            if path.endswith("/branches/" + retire.NAME) and api.branch_reads:
                api.branch["commit"]["sha"] = "updated-in-between"
            return orig(path, method)
        api.request = changing
        with self.assertRaises(RuntimeError):
            retire.run(api, execute=True)
        self.assertEqual(api.deletes, [])


if __name__ == "__main__":
    unittest.main()
