# Safe cleanup of merged GitHub branches

Use `scripts/cleanup_merged_branches.py` from any checkout with Python 3.9+ and an authenticated `gh` CLI, or set `GH_TOKEN` / `GITHUB_TOKEN` with repository metadata read and contents write permissions.

## Preview first (default: no deletion)

```bash
python3 scripts/cleanup_merged_branches.py --repo JinHaocong/nas-file-center
```

By default this retains a branch for **at least 7 days after merge**. For Console-specific branches:

```bash
python3 scripts/cleanup_merged_branches.py --repo JinHaocong/nas-file-center --prefix feat/console-v2-
```

After reviewing `CANDIDATE` and `KEEP` lines, actually delete eligible remote refs with the opt-in flag:

```bash
python3 scripts/cleanup_merged_branches.py --repo JinHaocong/nas-file-center --execute
```

To deliberately include freshly merged branches, pass `--min-age-days 0 --execute`; this is **not** the default.

## Safety invariants

- Never select the GitHub default branch, main/master, develop, staging, production, release, hotfix, stable prefixes or GitHub-protected branches.
- Only same-repository PR heads whose merge commit records target the default branch; current branch SHA must **equal** the merged PR head SHA. Squash-merges work because the PR head remains recorded.
- If any PR on that branch is open or unmerged/closed without merge, leave it for manual review.
- Enumerate **all** paginated PRs and branches; stop on API errors instead of guessing.
- Before each deletion, fetch the current branch SHA/protected status and all currently open PRs again; skip if anything changed.
- Dry-run is the default. Nothing is deleted without `--execute`.
- No tags, local git branches, artifacts, PR records or production files are changed by this script.

Unit test without GitHub access:

```bash
python3 scripts/tests/test_cleanup_merged_branches.py
```

This script is provided but **not executed with --execute** as part of PR #186. It is a manual maintenance tool, not a deployment action.
