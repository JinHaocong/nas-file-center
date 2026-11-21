# GLOSSARY — NAS File Center Media Organization

This file gives coding agents a shared domain vocabulary for the approved Media Organizer V1.6 feature. Do not change definitions implicitly during implementation. See docs/superpowers/specs/2026-11-17-media-organizer-v1.6-design.md.

| Term | Precise meaning | Do not confuse with |
|---|---|---|
| MediaPackage package | A fixed-boundary resource package under the configured MediaPackage root; managed by the existing specialist planner | An arbitrary media file whose basename contains a source label |
| semantic unit | A discovered independent work/package within the selected Else scope to which V1.6 grouping and numbering apply | An author or collection root by default |
| Semantic boundary | Directory preserving collection/source batch/work/version identity; its children may be scanned, not flattened across it | A disposable classification wrapper |
| Classification wrapper | Old P/V/other-language classification directory proven to have no independent work/version meaning | Any directory named P, P1, photos or video irrespective of structure |
| Flatten | Move all pure same-kind media (1–200) into current unit root and allocate 001-based filenames | Skip unchanged pure folders merely because they have ≤200 files |
| Bucket | A named P, V or Other group with actual item count and metadata-derived byte size; P/V capacity ≤200 | A hard threshold on total images+videos combined |
| Canonical layout | Complete deterministic set of final relative paths, file ordinals, bucket labels and wrapper cleanup for a unit | Whether a basename happens to look numeric |
| Already organized | Canonical layout matches live source identities and placements, with no stale wrappers or invalid labels; 0 changes | Any unit containing one directory named P |
| Frozen plan | Reviewed immutable source/target/identity snapshot to be checked again before mutation | A preview result executed without a recheck |
| No-replace publish | A staging/publishing operation that cannot clobber pre-existing non-input destinations | Normal os.rename overwrite |
| Other | Regular file whose **last** extension is neither recognized image nor video; follows current MediaPackage Other policy | A sidecar inferred from its stem |
| TDD Red | A new behavior test fails for the expected missing functionality before implementation | A test that fails from a setup/import bug |
| TDD Green | Minimum implementation makes that test pass with unaffected regression tests | Changing tests until old code passes |
| Tracer bullet | One reviewable vertical slice through a working behavior, its tests, and minimal required seam | One broad phase such as “all backend” or “all frontend” |

## Safety invariants

- A read-only preview must never mutate the selected root.
- The expected target must remain within the current organizing unit.
- Unknown semantic edges are blockers, not permission to flatten.
- Media items always get stable 001-based ordinals, regardless of pre-existing collisions.
- Already canonical units produce no moves, renames or staging.
- All moves require protected path checks, frozen identities, no-replace staging/publishing, an authenticated Worker lease and a recoverable journal.
- Never use real/private media filenames as public test fixtures or telemetry.
