# Gate5-G / G7 Independent Implementation-Plan Review (v1.1.1)
# Final Implementation Plan Review Findings Archive

**Date:** 2026-09-11  
**Target Release:** NAS File Center v0.3.5  
**Branch:** `v0.3.5-gate5c-hotfix4`  
**Baseline Plan HEAD:** `1500e54207719fa21e5b71055378e997ea38526b`  
**Frozen Architecture HEAD:** `0ddf932747021578f08843c5069ef88a461d493f`  
**Production Code Baseline HEAD:** `c32d0778c59add81e0c296d6f73aa66bc403c04f`  
**Review Verdict:** **FAILED / REVISION-1.1.2 FINAL CLOSURE REQUIRED**  

---

## 1. Executive Summary

The Independent Reviewer evaluated **Implementation Plan v1.1.1** against the frozen Revision 3.1 Architecture Amendment (`0ddf932`). While significant progress was acknowledged, 8 concrete implementation discrepancies and fidelity gaps were identified. Implementation authorization remains withheld until these items are closed in **Implementation Plan v1.1.2**.

---

## 2. Authoritative Review Findings

### Finding 1: Candidate Qualification Must Validate `st_ctime_ns`
- **Defect**: v1.1.1 pseudocode checked `st_dev`, `st_ino`, `st_size`, and `st_mtime_ns`, but omitted `st_ctime_ns`.
- **Baseline Truth**: [`app/tasks/handlers.py::gather_reconcile_evidence()`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py#L510-L532) and `_validate_evidence()` strictly mandate pre-hash and post-hash verification of `st_ctime_ns` to detect concurrent metadata/permission mutations.
- **Mandatory Closure**:
  - Update candidate qualification API to consume full Gate3 frozen evidence (`dev`, `ino`, `size`, `mtime_ns`, `ctime_ns`, and `content_hash`).
  - Pre-hash check: `S_ISREG`, expected dev, ino, size, mtime_ns, ctime_ns.
  - Post-hash check: verify `st_dev`, `st_ino`, `st_size`, `mtime_ns`, `ctime_ns` are completely unchanged during 1MiB SHA256 chunk streaming.
  - Add RED tests: `test_candidate_rejects_expected_ctime_mismatch` and `test_candidate_rejects_ctime_change_during_hash`.

### Finding 2: Candidate Qualification Mismatch Must Enter Conflict
- **Defect**: DB-lag Variant #2 previously suggested retrying with generation $G+1$ upon qualification failure.
- **Architecture Requirement**: Under Frozen Architecture Section C2/C2.1, when candidate anchor exists but fails qualification, it represents an unexpected physical reality. It must transition immediately to `state='conflict'`, `tx_phase='conflict'`.
- **Mandatory Closure**:
  - Candidate anchor preserved in place. Zero unlink. Zero new generation retry. Zero publication. Zero source capture.

### Finding 3: Restore Must Not Finalize Before Public View Retirement
- **Defect**: Variants #10, #11, and #13 allowed setting `state='restored'` before public quarantine view retirement.
- **Architecture Requirement**: `restored` state strictly requires: original path published from authoritative anchor AND public quarantine view successfully retired/captured AND authoritative anchor intact.
- **Mandatory Closure**:
  - `restoring` + original absent: execute `link(anchor, original)`; remain `state='restoring'`, `tx_phase='restoring'`.
  - `restoring` + original present expected: capture public quarantine view by rename into restore attempt slot. Only after view is retired: `state='restored'`, `tx_phase='restored'`.
  - If captured view is foreign/unknown: preserve in place, mark `state='conflict'`, `tx_phase='conflict'` (do NOT mark restored).
  - Update R14 expected result to reflect conflict when public view is foreign.

### Finding 4: Capability Probe Must Target the Actual Target Filesystem
- **Defect**: Passing `dir_path=target_dir` into `_probe_rename_noreplace_supported()` internally executes `os.path.dirname(target_dir)`, thereby probing the parent directory instead of `target_dir` itself.
- **Mandatory Closure**:
  - Open target directory via `safe_open_parent_fd` and probe via descriptor: `_probe_rename_noreplace_supported(dir_fd=target_dir_fd)`.
  - Add a dedicated test proving the probe exercises `target_dir` directly, not its parent.
  - Before admitting `COMPAT_TRANSACTIONAL`, verify `source st_dev == target_tx st_dev == public st_dev`; fail closed with `EXDEV`/`EOPNOTSUPP` if disparate.

### Finding 5: Worker Lease Helper Signature Must Match Codebase Idiom
- **Defect**: v1.1.1 assumed a global `SessionLocal` in `app/tasks/recovery.py`.
- **Baseline Truth**: Recovery functions in `app/tasks/recovery.py` explicitly take `session_factory: sessionmaker`.
- **Mandatory Closure**:
  - Freeze signature: `renew_and_assert_worker_lease(session_factory: sessionmaker, worker_id: str, timeout_seconds: float = WORKER_LEASE_TIMEOUT_SECONDS) -> None`.
  - Execute committed fence under `with session_factory() as session:`, issuing `BEGIN IMMEDIATE`, updating `acquired_at`, and committing before return.

### Finding 6: Restore Module is Modify, Not Create
- **Defect**: Task 8 listed `Create: app/quarantine/restore.py`.
- **Baseline Truth**: [`app/quarantine/restore.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/quarantine/restore.py) already exists in baseline `c32d077` with critical validation functions (`validate_restore_destination_intent`, `verify_quarantine_source_integrity`).
- **Mandatory Closure**:
  - Update Task 8 to `Modify: app/quarantine/restore.py`. Integrate transactional restore into the existing module.

### Finding 7: NAS Acceptance Path Must Use Real Verified zfuse Paths
- **Defect**: Referenced invented paths (`/mnt/zfpool/...`, `/volume1/...`).
- **Baseline Truth**: Real NAS paths verified in Gate5-G hotfixes are:
  - `PRODUCTION_DATA_PATH = /tmp/zfsv3/sata11/15246330601/data`
  - `PRODUCTION_CONFIG_PATH = /tmp/zfsv3/nvme13/15246330601/data/NasFileCenter`
  - `VERIFIED_DISPOSABLE_PARENT = /tmp/zfsv3/nvme13/15246330601/data`
  - `OLD_FAILURE_EVIDENCE_ROOT = /tmp/zfsv3/nvme13/15246330601/data/gate5g_isolated_testbed`
  - `OLD_HOTFIX_PROBE_ROOT = /tmp/zfsv3/nvme13/15246330601/data/gate5g_hotfix1_probe`
- **Mandatory Closure**:
  - Validation root must be sibling: `/tmp/zfsv3/nvme13/15246330601/data/gate5g_candidate_<sha_short>`.
  - Fail-closed guards against production paths and old failure evidence roots.
  - Sudo enforcement, `stat -f` zfuse check, sentinel check, zero execution during planning.

### Finding 8: State Model Cleanup — Remove Invented `state='failed'`
- **Defect**: Included `state='failed'` which is not in the frozen architecture or existing `QuarantineEntry.state` lifecycle.
- **Mandatory Closure**:
  - Aborted / failed transactions must transition to `state='conflict'`, `tx_phase='conflict'`.
  - Maintain exact 12-state matrix (`preparing`, `active`, `restoring`, `restored`, `conflict`, plus legacy states).
