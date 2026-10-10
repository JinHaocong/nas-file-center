# Console v2 — native Scan Creation Form (DirectoryPicker preserved)

## Scope

- Extract Scan creation into a dedicated `ScanCreateModal` with native
  HTML input, textarea, checkbox and form, ConsoleButton and Lucide icons.
- Shared model `scan_create.ts` validates name/roots and converts the
  form into the exact existing Scan API payload: name, roots, isolate,
  min_size, name_patterns, exclude_patterns.
- Preserve the default Scan-YYYY-MM-DD task name, isolate default=false,
  optional minimum-size and per-line include/exclude patterns.
- Keep `DirectoryPicker multiple` and its browser/favorites/recent paths,
  manual multi-line input, and existing `ALLOWED_ROOTS` guard enforced by
  the backend. UI does not invent filesystem/path validation authority.
- Prevent closing/double-submit while API request is pending. Keep success/
  error notifications, both cache invalidations and scan-detail navigation.
- Scan History now has no direct Ant Design imports; the extracted creation
  modal retains **only the Ant Modal overlay** until the nested
  DirectoryPickerModal is safely migrated with it.
- Five new focused regression tests, plus updated historical Scan History
  tests and responsive light/dark form styles.

## Why the modal stays Ant temporarily

The existing DirectoryPicker's nested browser, favorites, recents and
multi-select confirmation is also an Ant Modal. Mounting it inside a new
Radix Dialog while leaving the nested picker unchanged could break portal
z-index, focus trapping and keyboard access. A later atomic migration of
DirectoryPickerModal + the outer modal will handle focus and layering
together. Replacing the picker with a plain input is **not acceptable**.

## Security and deployment boundary

No backend changes, no writes to NAS files, no Scan/Plan/Quarantine/Worker
execution changes. The server remains authoritative for all path checks,
including `ALLOWED_ROOTS`. All active Scan Jobs and dependent Plan
protections remain unchanged.

Owner requested **one final UI visual acceptance**, not per-PR signoff.
CI still gates merges, no automatic deployment to NAS.
