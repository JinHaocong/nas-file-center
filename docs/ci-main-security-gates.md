# CI and GitHub Main Branch Safety Gates

Status: **source-side workflow hardening; repository branch protection still requires an explicit GitHub settings change**  
Product baseline: **v0.4.7**  
Initial source baseline: `main@f73b6a8baf77ffaca41e196c690913ea52161695`

## 1. Scope and authority

This change is limited to CI workflow definitions and operational documentation. It does **not** change application code, authentication, database schema, API contracts, Docker deployment, Worker state, quarantine/purge/restore, or filesystem mutation authority.

The existing Release Validation workflow now also runs on every `main` push (including merges), preserving its PR and `release/v0.4.7` triggers. It runs:
- release-version consistency and full backend regression;
- frontend test suite, typecheck and production build;
- linux/amd64 Docker build and runtime checks.

The new Dependency Audit workflow runs for PRs targeting `main`, pushes to `main`, weekly on the default branch, and manual dispatch. It installs the exact frontend lockfile without lifecycle scripts and fails on **moderate, high or critical production dependency advisories** using `npm audit --omit=dev --audit-level=moderate`.

The audit deliberately does not auto-fix dependencies or edit a lockfile. If new advisories are disclosed, inspect and address them in a separate reviewed PR, preserving product behavior.

## 2. Branch protection — administrator action still required

Workflow files alone **do not protect a Git branch**. Before treating this as an enforced PR gate, a repository administrator must configure a rule/ruleset targeting `main` under GitHub **Settings → Branches** or **Settings → Rules → Rulesets**.

Recommended minimum configuration:

1. Require a pull request before merging; disable direct pushes for normal contributors.
2. Require successful status checks from the proposed PR's **final exact head SHA**, and require branches to be up to date before merge (or use a merge queue when available).
3. Once their exact names are confirmed from a completed PR run, require:
   - `Release Validation / regression`
   - `Release Validation / linux-amd64-docker`
   - `Dependency Audit / production-dependencies`
4. Block force pushes and branch deletion. Apply restrictions to administrators/bypass users as appropriate to the repository policy.
5. Resolve pending review discussions and require independent review for high-risk filesystem, deletion, auth, or migration changes.

**Important:** Do not require a path-filtered job such as `UI Validation` for *all* PRs: if it is skipped because no frontend paths changed, a required status check may remain pending. The three checks above use workflows without PR path filters.

If the repository's GitHub plan does not support the desired rule on a public repository, use the strongest available native protection and record any remaining gap; do not claim protection is active without a fresh GitHub configuration read.

## 3. Evidence / merge policy

- Record the exact source `main` SHA before beginning.
- Create a feature branch; do not push directly to `main`.
- Check the PR's exact final head SHA and every relevant GitHub Actions job for `completed/success` before merging.
- Use `expected_head_sha` when calling GitHub merge.
- After merge, verify `main` moved to the expected merge SHA and inspect the **post-merge `main` push** Release Validation and Dependency Audit results.
- A green PR checks result does not automatically mean the merge-commit checks have run.

The weekly dependency scan may begin failing on newly published advisories without code changes; treat this as new security evidence, not an automatic reason to rewrite application logic.

## 4. Real-NAS and release boundaries

GitHub-hosted CI and linux/amd64 Docker evidence are **not** real zfuse acceptance. Organizer C5 and Scheduler S5 remain subject to their own isolated real-NAS gates, with exact commit identity and zero-residue evidence. Hardlink/Reflink availability must be positively proven against the actual filesystem path pair.

Neither these CI changes nor a successful merge authorize a production Docker Hub push, Komodo redeploy, modification of production DATA/CONFIG, or deletion on the NAS.
