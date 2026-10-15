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
