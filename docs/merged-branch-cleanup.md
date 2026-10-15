# Merged PR remote branch cleanup

**Policy (owner-approved, 2026-10-15):** Once a same-repository PR is **merged
into `main`**, its source branch may be removed immediately; there is no
mandatory seven-day delay. Do not delete an open/unmerged PR, unknown/unmatched
branch, altered branch head, default/reserved/protected branch, or branch with
any unmerged/active PR history.

This is a **remote Git ref cleanup only**. It never rewrites `main`, removes
merged commits or PR history, deletes NAS content, or deploys the product.

## Command from repository root

Requires `gh auth login` or `GH_TOKEN`/`GITHUB_TOKEN` with repository
contents/write access to delete remote branches.

Preview all 0-day eligible refs **without deleting anything**:

```bash
python3 scripts/cleanup_merged_branches.py --repo JinHaocong/nas-file-center
```

Then execute only the approved candidates:

```bash
python3 scripts/cleanup_merged_branches.py --repo JinHaocong/nas-file-center --execute
```

Optional conservative retention, e.g. seven days:

```bash
python3 scripts/cleanup_merged_branches.py --repo JinHaocong/nas-file-center --min-age-days 7 --execute
```

The `--prefix` option limits candidates; `--execute` is always required
for destructive remote-branch deletion in the CLI.

## Automatic cleanup after merging to main

`.github/workflows/merged-branch-cleanup.yml` runs on a **push to `main`**
and supports an explicit manual `workflow_dispatch` from `main`. It uses
an ephemeral GitHub Actions token scoped to repository `contents: write` and
runs the same command first in dry-run mode and then in `--execute` mode;
the job summary and logs record each result.

Before deletion, the script checks all repository PR history, not just recently
merged PRs. Eligibility requires a same-repo merged PR into the current default
branch with an **exact match between current remote branch SHA and the PR head
SHA**. A closed but unmerged or open PR with that branch name blocks deletion.
It refuses archived repositories, protected/default/reserved branches and HEAD
changes, and checks current open PRs again immediately before each delete.
If token permissions, branch protection or a ruleset prevent deletion, the
workflow fails visibly instead of silently reporting success.

This automation is not a substitute for the PR latest-HEAD complete CI gate:
merge only after all checks/workflows on that exact PR head succeed. It also
does not represent real-NAS Organizer C5 / Scheduler S5 acceptance.

## Recovery

Deleted **branch refs** can be recreated from immutable merged PR head SHAs
if the commit objects still exist; `main` and the historical PR remain.
If a branch was intentionally retained without a merged PR, the cleaner reports
`KEEP ...: no same-repo merged PR`.

## Exceptional manually ported branch: Pure White foundation (2026-10-15)

The obsolete `design/pure-white-foundation-shell` branch was recreated as the
independent `design/pure-white-v21-foundation-on-current-main` PR #196, because
the archive recovery code had already moved the active base forward. PR #196
explicitly carried the original nine files (neutral palette, shell styles,
tests, acceptance and contract) onto current `main`, added the required
Archive Recovery layout and discreet release metadata, and was Squash Merged.
The old branch has 14 unique Git commit IDs because the port did not retain its
ancestry, **not** because the UI feature is still waiting to be merged.
The PR #196 merge commit is `29ee9a65d0bbaddb7ec5e48ccbaa1fff8bbc2ec4`.

Owner subsequently explicitly asked to resolve the stale branch (merge or
delete). Review against PR #196 and live `main` found no missing features;
re-merging would reintroduce older Dashboard/Plan styles and old release
metadata. Only this one exact ref is approved for retirement, at HEAD
`7abdcaddaada997e5f3cddbb6a8486786100223b`.

`scripts/retire_superseded_pure_white_branch.py` is an **exceptional
SHA-pinned, one-ref-only helper**, run in dry-run and execute modes only from
the post-main-push cleanup Action. Before deletion it verifies the repository
identity and default branch, non-protection, exact source SHA, merged PR #196
head and merge SHA, that the merged port is an ancestor of the live main,
no open PR from the original branch, and rechecks the same facts before the
DELETE REST call. Missing ref after successful cleanup is an idempotent no-op.
The general cleanup helper's strict PR-head equality policy remains unchanged.
No NAS operation, production deployment or direct push to `main` is involved.
