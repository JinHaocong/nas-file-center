# Console v2 — Phase 1: Mixed Dark Navigation + Light Workspace

Status: **first-phase implementation, not a full Ant Design removal**.
Visual direction: user-approved bespoke NAS File Center preview, 2026-10-09.

## Why

The previous frontend combines Ant Design components with many historic, progressively
overriding CSS skins. The product should no longer read as a generic admin template.
The target is a dark independent navigation shell and a bright, spacious operations
workspace with focused, readable tables and carefully differentiated safety states.

## Phase 1 implemented

- Desktop navigation, collapsed rail and mobile navigation become independent accessible
  React/HTML components (no Ant Design Sider, Menu, Drawer or icon imports).
- Header navigation, user/theme dropdowns and mobile dock use native React/HTML controls.
- Dashboard uses a bespoke hero, task/scanning cards, genuine API-backed metrics,
  native HTML activity tables, quick links to existing routes and honest recently
  observed task-state meters.
- Console outline icon bridge is local and dependency-free while the npm-lock-backed
  component migration is staged. This is **shadcn/ui-inspired**, not a claim that
  the shadcn CLI, Radix, Lucide React or Tailwind have already been installed.
- `console-v2.css` is one new scoped visual ownership layer applied last, with
  dedicated light/dark tokens and mobile breakpoints. Existing business screens
  remain operational while the legacy layers are systematically retired.

## Phase 2 / 3 next steps (not in this PR)

1. Adopt npm-lock-pinned Radix primitives and Lucide React; migrate the shared
   dialogs, form controls, badges and composable buttons.
2. Migrate business screens in workflows: Plans/Tasks → Scans/Dedupe → Organizer
   / Workflows → remaining tools. Replace Ant tables/forms with accessible custom
   controls or TanStack Table where pagination/large datasets require them.
3. Remove every runtime import from `antd` and `@ant-design/icons` and remove their
   packages + legacy stylesheet overrides only after replacements pass CI and
   real-browser visual review.

The user has explicitly chosen to **remove Ant Design eventually**. Do not treat
old notes claiming Ant must remain as current product decisions.

## Non-negotiable safety and truthfulness

- Preserve all routes, auth/session and API contracts.
- Never modify filesystem behavior, worker execution, Plan/Quarantine semantics,
  destructive-confirmation requirements or PathGuard in a UI migration.
- Dashboard must not invent disk capacity, history series, Worker counts or
  other telemetry absent from backend responses.
- Display Safe Mode, permanent-delete state and Worker/queue state visibly.
- Test 360/390/430px and tablet/desktop widths, keyboard navigation, scroll,
  light/dark contrast and reduced-motion preference.
- This PR does **not** redeploy the NAS.
