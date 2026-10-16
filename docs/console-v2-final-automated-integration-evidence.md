# Console v2 — Final Automated Integration Gate Evidence

Status: **automated integration evidence only**. This document does not approve
the visual design, production NAS, deployment, end-to-end operator actions, or
accessibility beyond the exercised automated assertions.

## Closure scope

The high-level checklist item `Full TypeScript, frontend unit/regression,
backend, Docker and dependency-audit gates` is an **automated source
integration gate**. Its closure requires the same exact PR HEAD to pass all of:

| GitHub workflow | Required checks and evidence |
| --- | --- |
| UI Validation | `frontend-validation` (`npm ci`, `npm test`, `npm run typecheck`, `npm run build`); `backend-regression` (`pytest -q`); `browser-overlay-smoke` (real Chromium / read-only synthetic fixtures) |
| Release Validation | `regression` (release-version consistency, full backend pytest, frontend tests, TypeScript, build); `linux-amd64-docker` (actual build and inspected linux/amd64 image, ffprobe, Pillow) |
| Dependency Audit | `production-dependencies` (`npm ci --ignore-scripts`, `npm audit --omit=dev --audit-level=moderate`) |
| Organizer Advanced C5 Closure | `closure-regression` (focused, synthetic acceptance, full backend, frontend); `linux-amd64-docker` (linux/amd64 candidate build) |

The eight PR Check Runs above belong to four PR Workflow Runs.
Every Check Run and Workflow Run must be `completed/success` for **the
latest PR HEAD**, not a previous commit. A subsequent commit invalidates the
previous pass. The PR base must remain stable and conflict-free.

This gate also fixes a provenance gap: GitHub's ordinary
`pull_request` checkout defaults to a synthetic merge ref. Every listed
source-testing job must now explicitly checkout the exact
`github.event.pull_request.head.sha || github.sha` and fail if
`git rev-parse HEAD` differs. Docker tags/evidence must use the actual
checkout identity, not the synthetic PR merge `GITHUB_SHA`.
`frontend/scripts/final-integration-gates.test.mjs` is executed by
`npm test` and protects those requirements against accidental regression.

## Verified pre-closure baseline (2026-10-16)

The preceding merged Stage 5E-AS PR #258 supplies independently retrievable
workflow results **before** the stricter checkout assertions were introduced.
These are historical starting evidence, not a claim that the new assertions
already ran:

- Exact PR HEAD: `56054f3a6ae79b5831dfc97a37604ffabe2453cf`
- PR Check Runs: **8/8 completed/success**; PR Workflow Runs: **4/4 completed/success**
- [UI Validation](https://github.com/JinHaocong/nas-file-center/actions/runs/38836095476) — frontend, backend, Chromium success
- [Release Validation](https://github.com/JinHaocong/nas-file-center/actions/runs/38836095479) — regression and Docker success
- [Dependency Audit](https://github.com/JinHaocong/nas-file-center/actions/runs/38836095500) — success
- [Organizer Advanced C5 Closure](https://github.com/JinHaocong/nas-file-center/actions/runs/38836095455) — regression and Docker success
- Merged `main`: `e4ceee710093f31df71266b7ae52ef62ee72ba05`
- `main` Check Runs: **4/4 success**; Workflow Runs: **3/3 success**
- [Main Release Validation](https://github.com/JinHaocong/nas-file-center/actions/runs/38837438680)
- [Main Dependency Audit](https://github.com/JinHaocong/nas-file-center/actions/runs/38837438734)
- [Main Branch Cleanup](https://github.com/JinHaocong/nas-file-center/actions/runs/38837438681)

## Final closure procedure

The changed checkout/evidence checks must also run in the actual **closure
PR**. Mark this gate accepted only when (1) all required PR Check Runs and
Workflow Runs on its latest exact HEAD succeed, (2) the PR can be Squash
Merged into the inspected base, and (3) the new `main` completes its own
post-merge Release Validation / Dependency Audit / Branch Cleanup gates.

No test is made optional, disabled, or changed to `continue-on-error`.
The safe synthetic browser matrix never contacts the production NAS.

## Still deliberately not closed

- Global shared Dialog/Select/Checkbox/Form/destructive-control ownership.
- Historical CSS consolidation and maintainable theme ownership.
- Exhaustive eight-width visual review and original NAS visual discrepancy.
- Full keyboard/focus/reduced-motion/dark-contrast **human accessibility review**.
- Real NAS acceptance in a separately authorized safe test environment.
- Owner's single consolidated visual approval and explicit deployment.

A successful CI only establishes the narrower automated integration gate. It
does **not** replace those six independent high-level items.
