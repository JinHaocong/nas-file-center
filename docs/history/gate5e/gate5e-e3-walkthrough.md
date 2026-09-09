# Gate5-E / E3 One-Level Flatten Walkthrough

## Goal
Implement the new canonical batch utility action `flatten_one_level` strictly following the approved E3 Contract and Implementation Plan.

## Changes Made
1. **Schema Definition**: Added `FlattenOneLevelAction` to `app/batch_utilities/schema.py` which strictly mandates absolute wrapper paths and rejects lexical duplicates. Updated `BatchUtilityAction` union and `BatchUtilityPreviewResponse` utility_action fields.
2. **Discovery Logic**: Implemented `discover_flatten_one_level` in `app/batch_utilities/flatten.py` which executes live discovery via `os.scandir`. Captures `OSError` as `SCANDIR_FAILED` and gracefully handles non-file/dir objects with `UNSUPPORTED_OBJECT` and direct symlinks with `WRAPPER_CHILD_SYMLINK`.
3. **Topology Graph Resolution**: Created `resolve_flatten_graph` in `app/batch_utilities/flatten_graph.py`. Incorporates physical duplicate wrapper overlapping detection (`BATCH_UTILITY_SCOPE_OVERLAP`) via `check_wrapper_overlap` and uses existing target resolution features from `app.path_safety.validate_mutation_destination` ensuring safety boundaries are respected.
4. **Compiler Integration**: Created `compile_flatten_one_level_preview` in `app/batch_utilities/compiler.py` establishing proper Phase A capabilities, mapping items safely through topological check, creating preview responses, and generating draft `BatchUtilityDraftIntent` items using `move`.
5. **Lifecycle Constraints**: Ensured Phase B explicitly branches into flattening paths with zero `os.scandir` reliance, preserving filesystem integrity. Re-used `BatchUtilitySymlinkBlockedError` and related machinery globally through standard HTTP responses.

## Verification
- Added `test_gate5e_e3_schema.py`
- Added `test_gate5e_e3_discovery.py` 
- Added `test_gate5e_e3_graph.py`
- Added `test_gate5e_e3_compiler.py`

Full suite (`E1`, `E2`, `E3` integration) executed and passes 100% of targets successfully in Dockerized Python 3.12-slim environment.
