# Console v2 Phase 2B — Native administrator security dialog

The user will conduct **one visual acceptance at the end of the UI migration**.
Automated CI still gates each independent PR.

## Scope

- Replace the Ant Design password-change `Modal`, `Form`, `Input.Password`
  and old lock icon with an accessible native HTML `dialog`.
- Preserve the existing authenticated `authApi.changePassword` payload,
  validation, password clearing, pending-request lock and session message.
- Add a reusable native toast feedback provider with semantic alert/status
  announcements and timeout cleanup.
- Add light/dark, mobile and reduced-motion styling.
- Keep reusable `ConsoleButton` from the previous phase.
- Add testable validation and focused CI tests for every error class.

## Security boundary

No backend changes. No local storage of passwords; passwords remain in
component memory until submitted or cleared. Old and new passwords are sent
only through the preexisting authenticated API. Escape and closing controls
cannot dismiss an in-flight request. Browser-native dialog focus handling
provides modality.

No changes to filesystem mutations, Plan approvals, permanent-delete
confirmations, Quarantine, Worker state, login or API authorization.

## Remaining migration

Other legacy Ant Design modals and form controls remain pending. Not a claim
that the full Ant Design dependency has been removed.

No NAS deployment.
