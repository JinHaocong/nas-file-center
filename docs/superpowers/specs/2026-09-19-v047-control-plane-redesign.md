# v0.4.7 Control Plane Redesign

## Direction

The v0.4.6 glass workspace made the right side visually consistent, but it also promoted too many ordinary content regions into floating cards. v0.4.7 changes the hierarchy rather than adding more decoration.

The sidebar remains the visual anchor. The right workspace becomes a flatter, denser control-plane canvas:

- shell depth is reserved for the sidebar, command rail, drawers, modals and popovers;
- PageHeader is an unboxed title/action band;
- DataPanel defaults to a restrained structural boundary rather than a floating card;
- dense data pages let tables become the primary surface;
- metrics read as one instrument strip rather than unrelated cards;
- glass is selective shell chrome, not a workspace-wide material;
- radius, blur and shadow are reduced in ordinary content;
- mobile is composed independently around title/actions/data density rather than stacking desktop cards.

## Reference patterns distilled

The redesign intentionally combines patterns rather than copying one project:

- Supabase Studio: explicit PageContainer/PageHeader/PageSection ownership, dense professional data tooling.
- Twenty: sidebar-first workspace, table/view-centric primary content, command-menu and side-panel patterns.
- Plane: restrained operational hierarchy and compact issue/data surfaces.
- Immich: strong application shell and high-density content without excessive nested cards.
- Open WebUI: desktop-like navigation and settings side-navigation.
- CasaOS / Runtipi / Homarr: self-hosted operational context, status-at-a-glance and approachable NAS/home-server shell patterns.
- Portainer: infrastructure vocabulary, operational tables and status/action separation.

## Phase 1

This commit establishes the new visual substrate only. It does not alter filesystem, plan, quarantine, worker or API semantics.

1. New v0.4.7 stylesheet entry.
2. New neutral/opaque workspace tokens with selective shell glass.
3. Integrated command rail header.
4. Unboxed PageHeader.
5. Flat DataPanel hierarchy.
6. Instrument-strip MetricCard composition.
7. Flatter tables, controls, tabs and pagination.
8. Responsive rules updated around the new hierarchy.
9. UI Validation enabled for the v0.4.7 branch.

Subsequent phases will audit and reshape page composition page-by-page rather than relying on global overrides.
