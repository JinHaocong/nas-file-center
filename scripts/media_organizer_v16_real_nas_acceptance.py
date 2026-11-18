#!/usr/bin/env python3
"""Disposable V1.6 real-NAS acceptance; all generated files stay under --root.

This intentionally validates only:
* real-mount flat-file primitives (via the capability probe),
* pure-media flat publication using retained inode-bound hardlinks,
* mixed P/V plans failing closed before public group promotion.

It does NOT enable or claim grouped P/V execution, final cleanup, or zero-change
second scan. Test fixtures and receipts are deliberately retained for manual
inspection/deletion as one uniquely named directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

from app.batch.media_organizer_capability_probe import probe_semantic_organizer_mount
from app.batch.media_organizer_deferred_cleanup import (
    DeferredCleanupConflict,
    record_deferred_cleanup_evidence,
    validate_deferred_publication,
)
from app.batch.media_organizer_manifest import (
    build_frozen_preview_manifest,
    save_frozen_preview_manifest,
)
from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch.media_organizer_publish import (
    PublishingConflict,
    publish_frozen_stage,
)
from app.batch.media_organizer_stage import stage_frozen_sources


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _assert_inside(path: Path, root: Path) -> None:
    if not path.resolve(strict=False).is_relative_to(root.resolve(strict=True)):
        raise RuntimeError(f"test path escaped authorized root: {path}")


def _manifest(unit: Path, private: Path, *, job_id: int, allowed_root: Path) -> tuple[dict, Path]:
    preview = preview_semantic_unit(unit, allowed_roots=[allowed_root])
    if preview.get("status") != "ready":
        raise RuntimeError(f"synthetic preview was not ready: {preview}")
    manifest = build_frozen_preview_manifest(
        unit, preview_record=preview, allowed_roots=[allowed_root], job_id=job_id,
    )
    manifest["cleanup_policy"] = "deferred"
    frozen = private / f"{job_id}.manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    return manifest, frozen


def run(root: Path, organizer_root: Path, candidate_sha: str) -> dict:
    root = root.resolve(strict=True)
    organizer_root = organizer_root.resolve(strict=True)
    if not organizer_root.is_relative_to(root):
        raise RuntimeError("organizer acceptance directory escaped authorized root")
    if not stat.S_ISDIR(os.lstat(root).st_mode) or not stat.S_ISDIR(os.lstat(organizer_root).st_mode):
        raise RuntimeError("acceptance roots must be real directories, not symlinks")
    if os.path.islink(root) or os.path.islink(organizer_root):
        raise RuntimeError("symlink acceptance root is forbidden")

    # Keep the evidence directory and all synthetic source/stage/public files
    # in the user-created SATA acceptance folder. Never auto-delete this run.
    run_dir = Path(tempfile.mkdtemp(
        prefix=f".nfc-v16-run-{candidate_sha[:12]}-",
        dir=organizer_root,
    ))
    os.chmod(run_dir, 0o700)
    run_stat = os.lstat(run_dir)
    if not stat.S_ISDIR(run_stat.st_mode) or stat.S_IMODE(run_stat.st_mode) & 0o077:
        raise RuntimeError("new acceptance run directory is not private")
    private = run_dir / "private"
    private.mkdir(mode=0o700)
    report: dict = {
        "candidate_sha": candidate_sha,
        "result": "FAIL",
        "acceptance_root": str(root),
        "organizer_root": str(organizer_root),
        "run_directory": str(run_dir),
        "artifacts_retained_for_manual_cleanup": True,
        "grouped_publication_authorized": False,
        "namespace_exclusive_custody_proven": False,
    }

    # Probe the actual SATA mount using random private scratch, and retain the
    # complete field-by-field evidence. The probe itself only removes entries
    # whose exact ownership witnesses it created.
    probe = probe_semantic_organizer_mount(root)
    report["filesystem_probe"] = probe
    if probe.get("grouped_publication_authorized") is not False:
        raise RuntimeError("probe must never authorize grouped publication")
    if probe.get("namespace_exclusive_custody_proven") is not False:
        raise RuntimeError("probe must not claim exclusive namespace custody")
    if probe.get("cleanup_complete") is not True:
        report["result"] = "FAIL_PROBE_RESIDUE"
        return report

    allowed_roots = [run_dir]
    flat_unit = run_dir / "flat-pure-media"
    flat_unit.mkdir(mode=0o700)
    (flat_unit / "a.jpg").write_bytes(b"nfc-v16-real-nas-image-a")
    (flat_unit / "b.png").write_bytes(b"nfc-v16-real-nas-image-b")
    flat_hashes = {
        "a.jpg": _sha(flat_unit / "a.jpg"),
        "b.png": _sha(flat_unit / "b.png"),
    }
    flat_manifest, flat_frozen = _manifest(
        flat_unit, private, job_id=160601, allowed_root=run_dir,
    )
    report["flat_flow"] = {
        "preview_operation": flat_manifest["operation"],
        "planned_files": len(flat_manifest["moves"]),
        "capability_compatible": probe.get("flat_filesystem_capabilities_compatible") is True,
    }
    if flat_manifest.get("operation") != "flatten_pure_media" or flat_manifest.get("groups"):
        raise RuntimeError("pure-media fixture unexpectedly requires grouped output")

    if probe.get("flat_filesystem_capabilities_compatible") is True:
        validate_deferred_publication(flat_manifest)
        stage_frozen_sources(
            flat_manifest, frozen_manifest_path=flat_frozen,
            allowed_roots=allowed_roots, lease_fence=lambda: None,
        )
        publish_frozen_stage(
            flat_manifest, frozen_manifest_path=flat_frozen,
            allowed_roots=allowed_roots, lease_fence=lambda: None,
            defer_directory_cleanup=True,
        )
        handoff = record_deferred_cleanup_evidence(
            flat_manifest, frozen_manifest_path=flat_frozen,
            allowed_roots=allowed_roots, lease_fence=lambda: None,
        )
        if (handoff.get("files_published") != 2
                or handoff.get("original_sources_retained") != 2
                or handoff.get("staged_links_retained") != 2
                or handoff.get("manual_cleanup_required") is not True
                or handoff.get("finalized") is True):
            raise RuntimeError(f"unexpected deferred handoff: {handoff}")
        identities = []
        for row in flat_manifest["moves"]:
            original, staged, final = (
                Path(row["source"]), Path(row["target"]), Path(row["final"]),
            )
            _assert_inside(original, run_dir)
            _assert_inside(staged, run_dir)
            _assert_inside(final, run_dir)
            expected_hash = flat_hashes[original.name]
            if not (original.is_file() and staged.is_file() and final.is_file()):
                raise RuntimeError("original/staged/public hardlink is missing")
            if not (_sha(original) == _sha(staged) == _sha(final) == expected_hash):
                raise RuntimeError("SHA-256 mismatch across original/stage/public paths")
            ids = {
                (p.stat().st_dev, p.stat().st_ino) for p in (original, staged, final)
            }
            if len(ids) != 1:
                raise RuntimeError("original/stage/public paths are not the same frozen inode")
            identities.append(list(next(iter(ids))))
        second = preview_semantic_unit(flat_unit, allowed_roots=allowed_roots)
        report["flat_flow"].update({
            "result": "PASS",
            "sha256_verified": True,
            "inode_identity_verified": True,
            "handoff": handoff,
            "second_preview_status": second.get("status"),
            "second_preview_needed_moves": second.get("needed_moves"),
            "second_scan_zero_change": False,
            "second_scan_blocked_until_manual_cleanup": second.get("status") == "blocked",
            "shared_inode_identities": identities,
        })
        if second.get("status") != "blocked" or second.get("needed_moves") != 0:
            raise RuntimeError(f"second preview did not fail closed as designed: {second}")
    else:
        report["flat_flow"].update({
            "result": "SKIPPED_UNSUPPORTED_FILESYSTEM",
            "sha256_verified": False,
            "inode_identity_verified": False,
        })

    # Mixed-media plan: freeze real synthetic P/V files on this mount, then
    # prove deferred publication rejects before creating a public group.
    mixed_unit = run_dir / "mixed-media"
    mixed_unit.mkdir(mode=0o700)
    (mixed_unit / "picture.jpg").write_bytes(b"nfc-v16-real-nas-picture")
    (mixed_unit / "movie.mp4").write_bytes(b"nfc-v16-real-nas-movie")
    mixed_hashes = {
        "picture.jpg": _sha(mixed_unit / "picture.jpg"),
        "movie.mp4": _sha(mixed_unit / "movie.mp4"),
    }
    mixed_manifest, mixed_frozen = _manifest(
        mixed_unit, private, job_id=160602, allowed_root=run_dir,
    )
    if not mixed_manifest.get("groups"):
        raise RuntimeError("mixed-media fixture did not create P/V groups")
    try:
        validate_deferred_publication(mixed_manifest)
    except DeferredCleanupConflict as exc:
        if "SEC-12" not in str(exc):
            raise
        grouped_result = "BLOCKED_BEFORE_STAGING"
    else:
        raise RuntimeError("SEC-12 grouped publication was not blocked")

    # If flat filesystem capabilities are available, also stage the frozen
    # mixed sources and call the actual publisher. It must reject before any
    # public P/V directory promotion. The retained stage is evidence, not cleanup.
    if probe.get("flat_filesystem_capabilities_compatible") is True:
        stage_frozen_sources(
            mixed_manifest, frozen_manifest_path=mixed_frozen,
            allowed_roots=allowed_roots, lease_fence=lambda: None,
        )
        try:
            publish_frozen_stage(
                mixed_manifest, frozen_manifest_path=mixed_frozen,
                allowed_roots=allowed_roots, lease_fence=lambda: None,
                defer_directory_cleanup=True,
            )
        except PublishingConflict as exc:
            if "SEC-12" not in str(exc):
                raise
            grouped_result = "BLOCKED_BEFORE_PUBLIC_GROUP_PROMOTION"
        else:
            raise RuntimeError("publisher unexpectedly accepted a grouped plan")
        for row in mixed_manifest["moves"]:
            source, staged, final = (
                Path(row["source"]), Path(row["target"]), Path(row["final"]),
            )
            _assert_inside(source, run_dir)
            _assert_inside(staged, run_dir)
            _assert_inside(final, run_dir)
            if not source.is_file() or not staged.is_file():
                raise RuntimeError("mixed source/stage evidence is missing")
            if _sha(source) != mixed_hashes[source.name] or _sha(staged) != mixed_hashes[source.name]:
                raise RuntimeError("mixed source/stage SHA-256 mismatch")
            if (source.stat().st_dev, source.stat().st_ino) != (
                    staged.stat().st_dev, staged.stat().st_ino):
                raise RuntimeError("mixed source/stage inode mismatch")
            if final.parent.exists():
                raise RuntimeError("SEC-12 created a public P/V directory")
    else:
        grouped_result = "BLOCKED_BEFORE_STAGING_FILESYSTEM_UNSUPPORTED"
    report["grouped_flow"] = {
        "result": grouped_result,
        "grouped_publication_authorized": False,
        "public_group_created": False,
        "original_files_preserved": True,
    }
    report["result"] = (
        "PASS_FLAT_AND_GROUP_HOLD"
        if probe.get("flat_filesystem_capabilities_compatible") is True
        else "FAIL_FLAT_FILESYSTEM_CAPABILITY"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--organizer-root", type=Path, required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run(args.root, args.organizer_root, args.candidate_sha)
    except Exception as exc:
        report = {
            "candidate_sha": args.candidate_sha,
            "result": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
            "artifacts_retained_for_manual_cleanup": True,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("result") == "PASS_FLAT_AND_GROUP_HOLD" else 2


if __name__ == "__main__":
    raise SystemExit(main())
