# Console v2 — CSS ownership, staged retirement (PR #184)

The CSS migration is distinct from the completed **Ant Design dependency** retirement.
As of PR #183 the application has zero AntD dependencies, but historical CSS still
contains selectors for removed Ant components. Deleting broad history without a
browser pass would risk unintentionally altering the CSS cascade.

## Import and ownership order (actual `frontend/src/main.tsx`)

1. `src/index.css` — historical app defaults, older UI rules and accumulated
   v0.4.x amendments. It still contains dead `.ant-*` selectors.
2. `src/styles/v047.css` through `v056-right-workspace-v2.css` — older UI
   versions and workspace refinements. Keep them in existing order while their
   live native selectors and interactions are identified.
3. `src/styles/pages/settings.css` — current Settings page composition authority.
4. `src/styles/console-v2.css`, `console-v2-phase2.css`, and
   `console-v2-*.css` — owned native Console shell, primitives and page modules,
   loaded last. Their layout, dark-mode and responsive rules are retained.

**CSS cascade invariants:** do not reorder entrypoint imports, change specificity,
move a selector across media conditions or silently override `!important`. These
could change actual computed styles even when unit tests still pass.

## PR #184 — first safe cleanup

- Removed obsolete AntD-only styling from `src/styles/pages/settings.css`.
  Preserved native Settings grid, session panel, control layout and responsive
  rules, including native selectors in former mixed Ant/native selector groups.
- Removed the obsolete `.ant-tag` header status override in
  `src/styles/console-v2.css`, retaining native status variants and dark states.
- Introduced `scripts/check-console-css-ownership.mjs`, run by `npm test`, to
  reject new `.ant-*` CSS selectors in all 45 owned `console-v2*.css` files
  and the native Settings page CSS. Other historical styles remain out of
  scope and are not falsely declared clean.
- Added regression tests for ownership boundary, native Settings breakpoints,
  shell status/focus/dark behaviors, import ordering, and Plan/Settings authority.

## Deliberately pending work

- Audit remaining dead AntD CSS selectors in `src/index.css`,
  `styles/v048*.css`, `v054-premium-system.css` and
  `v056-right-workspace-v2.css`. Several historical tests still demand these
  selectors and must be updated to native semantic assertions before removal.
- Identify overwritten versus still-live native declarations across legacy
  versioned styles. Remove or relocate them in small, reviewed tranches, with
  computed-style evidence when selectors share a cascade.
- Complete a single consolidated **visual acceptance** at widths
  360/390/430/768/1024/1280/1440/1920 in light and dark modes, including
  keyboard focus, reduced motion, overflow, dialogs and destructive confirmation.
- Do not deploy, alter a NAS directory or change Preview/Plan/Worker security
  authority as part of CSS cleanup.
