# Gate6-A Dependency Security Disposition

Date: 2026-09-13

Candidate reviewed before this disposition: `e4244c70f172ebeb812e7cc1badfaaa9908cb167`

## Closure audit result

The Gate6-A closure workflow records `npm audit --omit=dev` as three moderate production dependency findings:

1. `echarts < 6.1.0` — Apache ECharts XSS in the `Lines` series tooltip path (`GHSA-fgmj-fm8m-jvvx`, `CVE-2026-45249`).
2. `react-router >= 6.0.0, < 7.18.0` — open redirect via attacker-supplied navigation paths (`GHSA-wrjc-x8rr-h8h6`, `CVE-2026-53669`).
3. `react-router >= 6.4.0, < 7.18.0` — constructor injection during Framework/Data Mode manual SSR hydration (`GHSA-337j-9hxr-rhxg`, `CVE-2026-53666`).

This file is a scope/risk disposition. It does **not** claim that `npm audit` is clean.

## Current-app reachability review

### ECharts finding

The current frontend uses ECharts in `frontend/src/pages/Dashboard/index.tsx` for pie/donut charts. The reviewed code does not instantiate a `lines` series, and the current tooltip uses an explicit fixed formatter string.

The upstream advisory requires the vulnerable `Lines` series tooltip path. Therefore the reviewed NAS File Center frontend does not currently expose the advisory's vulnerable rendering path.

The installed `echarts-for-react` lockfile version is `3.0.6`. The separately published malware advisory affecting `echarts-for-react` versions `3.1.7` and `3.2.7` is therefore not present in this candidate.

### React Router SSR hydration finding

The current frontend is a client-side SPA:

- `frontend/src/main.tsx` uses `ReactDOM.createRoot(...).render(...)`.
- `frontend/src/App.tsx` uses `BrowserRouter`.
- `frontend/src/router/index.tsx` uses declarative `<Routes>` / `<Route>` routing.
- No Framework/Data Mode manual SSR hydration path is part of the reviewed application.

The upstream advisory explicitly limits this constructor-injection issue to Framework/Data Mode applications doing manual SSR/hydration and says Declarative Mode is not impacted. Therefore this advisory is not reachable in the current deployment architecture.

### React Router open-redirect finding

The upstream issue requires an attacker-supplied path to reach React Router navigation mechanisms. The Gate6-A UI addition does not introduce such a path: the new navigation target is an internal `/plans/${plan.id}` route where `plan.id` is the server-generated plan identifier returned by the API after a successful digest-bound Draft request.

This disposition does not attempt to prove that every future application route can never accept untrusted navigation input. Because the installed React Router 6.x line remains inside the upstream affected range, the dependency must still be upgraded before final v0.3.6 release closure.

## Gate6-A decision

Do not perform ECharts 5→6 and React Router 6→7 major migrations inside Gate6-A's destructive-operation closure candidate unless an independent reviewer finds the current reachability analysis insufficient.

Reasoning:

- the three audit findings are not introduced by the Gate6-A filesystem mutation architecture;
- the currently reviewed ECharts and SSR vulnerable paths are not reachable;
- the Gate6-A-specific navigation addition is not attacker-controlled;
- two unrelated major frontend dependency migrations would materially expand the change surface of a high-risk permanent-delete gate after its implementation and regression work is already complete.

This is an explicit residual-risk disposition, not a waiver of the dependency findings.

## Required follow-up before v0.3.6 release closure

A separately reviewed security dependency upgrade must be completed before Gate6-G / final v0.3.6 release closure:

- upgrade ECharts to a version containing the `6.1.0` security fix or newer;
- migrate React Router / React Router DOM to a version outside all then-current affected ranges (at minimum the versions required by the active advisories at implementation time);
- preserve the current SPA routing semantics;
- run frontend tests, typecheck and production build;
- run `npm audit --omit=dev` and explicitly disposition any remaining production findings;
- smoke-test Dashboard charts and all application routes;
- do not alter Gate5-G / Gate6-A filesystem mutation semantics as part of that dependency migration.

Until that follow-up is closed, `npm audit --omit=dev` remains a known non-zero security signal and must not be represented as clean.
