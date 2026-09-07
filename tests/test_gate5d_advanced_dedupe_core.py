from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.planning.dedupe_config import (
    AdvancedDedupeConfig,
    DedupeFactorsConfig,
    MtimeFactor,
    PathPriorityFactor,
    PathPriorityRule,
    PreferredExtensionFactor,
    canonicalize_extension,
    compute_config_digest,
    validate_and_canonicalize_config,
)
from app.planning.dedupe_engine import (
    AdvancedDedupeResult,
    DedupeGroupSnapshot,
    DedupeMemberSnapshot,
    GroupDecisionResult,
    compute_decision_fingerprint,
    compute_group_fingerprint,
    run_advanced_dedupe,
)


# =========================================================================
# 1. Configuration & Validation Tests
# =========================================================================

def test_config_valid_default():
    config = AdvancedDedupeConfig()
    validated = validate_and_canonicalize_config(config)
    assert validated.schema_version == 1
    assert validated.selection_mode == "weighted"
    assert validated.factors.path_priority.enabled is False
    assert validated.factors.preferred_extension.enabled is False
    assert validated.factors.mtime.mode == "none"


def test_config_schema_version_invalid():
    with pytest.raises(ValueError, match="schema_version"):
        validate_and_canonicalize_config({"schema_version": 2})


def test_config_weight_bool_rejected():
    # In Python, isinstance(True, int) is True, so we must explicitly reject bool
    with pytest.raises(ValueError, match="weight.*cannot be boolean|integer required"):
        validate_and_canonicalize_config({
            "schema_version": 1,
            "selection_mode": "weighted",
            "factors": {
                "path_priority": {"enabled": True, "weight": True, "rules": []}
            }
        })

    with pytest.raises(ValueError, match="weight.*cannot be boolean|integer required"):
        validate_and_canonicalize_config({
            "schema_version": 1,
            "selection_mode": "weighted",
            "factors": {
                "mtime": {"mode": "newest", "weight": False}
            }
        })


def test_config_weight_bounds():
    with pytest.raises(ValueError, match="weight"):
        validate_and_canonicalize_config({
            "factors": {"path_priority": {"enabled": True, "weight": -1, "rules": []}}
        })

    with pytest.raises(ValueError, match="weight"):
        validate_and_canonicalize_config({
            "factors": {"preferred_extension": {"enabled": True, "weight": 10001, "extensions": []}}
        })


def test_config_rule_and_extension_limits():
    # > 64 rules rejected
    excess_rules = [{"scope": "absolute", "pattern": f"/p/{i}/*"} for i in range(65)]
    with pytest.raises(ValueError, match="rules.*limit|maximum 64"):
        validate_and_canonicalize_config({
            "factors": {"path_priority": {"enabled": True, "weight": 10, "rules": excess_rules}}
        })

    # > 64 extensions rejected
    excess_exts = [f"ext{i}" for i in range(65)]
    with pytest.raises(ValueError, match="extensions.*limit|maximum 64"):
        validate_and_canonicalize_config({
            "factors": {"preferred_extension": {"enabled": True, "weight": 10, "extensions": excess_exts}}
        })


def test_config_reserved_factors_rejected():
    for reserved in ["resolution", "bitrate", "dimensions"]:
        with pytest.raises(ValueError, match="DEDUPE_FACTOR_UNAVAILABLE"):
            validate_and_canonicalize_config({
                "factors": {reserved: {"enabled": True, "weight": 10}}
            })


def test_config_extension_canonicalization():
    assert canonicalize_extension(".JPG") == "jpg"
    assert canonicalize_extension("JPEG") == "jpeg"
    assert canonicalize_extension("  .tar.gz ") == "gz"
    assert canonicalize_extension(".bashrc") == ""
    assert canonicalize_extension("photo.jpeg") == "jpeg"

    config = validate_and_canonicalize_config({
        "factors": {
            "preferred_extension": {
                "enabled": True,
                "weight": 50,
                "extensions": [".JPG", "PNG", " .WEBP "],
            }
        }
    })
    assert config.factors.preferred_extension.extensions == ["jpg", "png", "webp"]


def test_config_digest_determinism():
    c1 = validate_and_canonicalize_config({
        "selection_mode": "weighted",
        "factors": {
            "path_priority": {"enabled": True, "weight": 100, "rules": [{"scope": "absolute", "pattern": "/a/*"}]},
            "mtime": {"mode": "newest", "weight": 50},
        }
    })
    c2 = validate_and_canonicalize_config({
        "selection_mode": "weighted",
        "factors": {
            "mtime": {"mode": "newest", "weight": 50},
            "path_priority": {"enabled": True, "weight": 100, "rules": [{"scope": "absolute", "pattern": "/a/*"}]},
        }
    })
    # Dict order in JSON doesn't change canonical digest
    assert compute_config_digest(c1) == compute_config_digest(c2)

    # But rule order MUST change digest
    c3 = validate_and_canonicalize_config({
        "selection_mode": "weighted",
        "factors": {
            "path_priority": {
                "enabled": True,
                "weight": 100,
                "rules": [
                    {"scope": "absolute", "pattern": "/a/*"},
                    {"scope": "absolute", "pattern": "/b/*"},
                ]
            }
        }
    })
    c4 = validate_and_canonicalize_config({
        "selection_mode": "weighted",
        "factors": {
            "path_priority": {
                "enabled": True,
                "weight": 100,
                "rules": [
                    {"scope": "absolute", "pattern": "/b/*"},
                    {"scope": "absolute", "pattern": "/a/*"},
                ]
            }
        }
    })
    assert compute_config_digest(c3) != compute_config_digest(c4)


# =========================================================================
# 2. Path Priority Scorer Tests
# =========================================================================

def test_path_priority_first_active_rule_wins():
    # Rule 0 matches candidate A. Rule 1 matches candidate B.
    # Because Rule 0 matches at least one candidate (A), Rule 0 is active, Rule 1 is ignored.
    config = validate_and_canonicalize_config({
        "factors": {
            "path_priority": {
                "enabled": True,
                "weight": 100,
                "rules": [
                    {"scope": "absolute", "pattern": "/data/master/*"},
                    {"scope": "absolute", "pattern": "/data/backup/*"},
                ],
            }
        }
    })

    group = DedupeGroupSnapshot(
        provenance_id=1,
        content_hash="hash_path_1",
        file_size=1024,
        members=[
            DedupeMemberSnapshot(
                absolute_path="/data/master/doc.pdf",
                relative_path="doc.pdf",
                scan_root_index=0,
                scan_root_path="/data/master",
                mtime_ns=1000,
                size=1024,
            ),
            DedupeMemberSnapshot(
                absolute_path="/data/backup/doc.pdf",
                relative_path="doc.pdf",
                scan_root_index=1,
                scan_root_path="/data/backup",
                mtime_ns=1000,
                size=1024,
            ),
        ],
    )

    res = run_advanced_dedupe([group], config)
    assert res.actionable_group_count == 1
    g_res = res.groups[0]
    assert g_res.recommended_keep.absolute_path == "/data/master/doc.pdf"
    assert g_res.quarantine_candidates == ["/data/backup/doc.pdf"]

    explain_a = next(m for m in g_res.members if m.absolute_path == "/data/master/doc.pdf")
    explain_b = next(m for m in g_res.members if m.absolute_path == "/data/backup/doc.pdf")
    assert explain_a.total_score == 100
    assert explain_b.total_score == 0
    assert explain_a.recommended_keep is True
    assert explain_b.recommended_keep is False


def test_path_priority_relative_rule_and_case_sensitivity():
    config = validate_and_canonicalize_config({
        "factors": {
            "path_priority": {
                "enabled": True,
                "weight": 80,
                "rules": [
                    {"scope": "relative", "pattern": "archive/*"},
                ],
            }
        }
    })

    # Case sensitive: "archive/*" should NOT match "Archive/*"
    group = DedupeGroupSnapshot(
        provenance_id=2,
        content_hash="hash_case_1",
        file_size=500,
        members=[
            DedupeMemberSnapshot(
                absolute_path="/vol1/Archive/f.txt",
                relative_path="Archive/f.txt",
                scan_root_index=0,
                scan_root_path="/vol1",
                mtime_ns=100,
                size=500,
            ),
            DedupeMemberSnapshot(
                absolute_path="/vol2/archive/f.txt",
                relative_path="archive/f.txt",
                scan_root_index=1,
                scan_root_path="/vol2",
                mtime_ns=100,
                size=500,
            ),
        ],
    )

    res = run_advanced_dedupe([group], config)
    g_res = res.groups[0]
    assert g_res.recommended_keep.absolute_path == "/vol2/archive/f.txt"


# =========================================================================
# 3. Preferred Extension Scorer Tests
# =========================================================================

def test_preferred_extension_fallback():
    config = validate_and_canonicalize_config({
        "factors": {
            "preferred_extension": {
                "enabled": True,
                "weight": 70,
                "extensions": ["jpg", "png", "webp"],
            }
        }
    })

    # Group has png and webp (no jpg). First matching configured extension is png.
    group = DedupeGroupSnapshot(
        provenance_id=3,
        content_hash="hash_ext_1",
        file_size=2048,
        members=[
            DedupeMemberSnapshot(
                absolute_path="/p/img.webp",
                relative_path="img.webp",
                scan_root_index=0,
                scan_root_path="/p",
                mtime_ns=100,
                size=2048,
            ),
            DedupeMemberSnapshot(
                absolute_path="/p/img.PNG",
                relative_path="img.PNG",
                scan_root_index=0,
                scan_root_path="/p",
                mtime_ns=100,
                size=2048,
            ),
        ],
    )

    res = run_advanced_dedupe([group], config)
    g_res = res.groups[0]
    assert g_res.recommended_keep.absolute_path == "/p/img.PNG"
    exp_png = next(m for m in g_res.members if m.absolute_path == "/p/img.PNG")
    exp_webp = next(m for m in g_res.members if m.absolute_path == "/p/img.webp")
    assert exp_png.total_score == 70
    assert exp_webp.total_score == 0


def test_preferred_extension_tar_gz_and_dotfile():
    config = validate_and_canonicalize_config({
        "factors": {
            "preferred_extension": {
                "enabled": True,
                "weight": 50,
                "extensions": ["gz", "tar"],
            }
        }
    })

    # archive.tar.gz -> extension is gz, not tar
    group = DedupeGroupSnapshot(
        provenance_id=4,
        content_hash="hash_tar_gz",
        file_size=100,
        members=[
            DedupeMemberSnapshot(
                absolute_path="/a/data.tar",
                relative_path="data.tar",
                scan_root_index=0,
                scan_root_path="/a",
                mtime_ns=10,
                size=100,
            ),
            DedupeMemberSnapshot(
                absolute_path="/b/data.tar.gz",
                relative_path="data.tar.gz",
                scan_root_index=1,
                scan_root_path="/b",
                mtime_ns=10,
                size=100,
            ),
        ],
    )

    res = run_advanced_dedupe([group], config)
    # gz is preferred over tar in config
    assert res.groups[0].recommended_keep.absolute_path == "/b/data.tar.gz"


# =========================================================================
# 4. mtime Scorer Tests
# =========================================================================

def test_mtime_newest_and_tie():
    config = validate_and_canonicalize_config({
        "factors": {
            "mtime": {"mode": "newest", "weight": 60}
        }
    })

    # Two members tie for newest (3000ns), one is older (2000ns)
    group = DedupeGroupSnapshot(
        provenance_id=5,
        content_hash="hash_mtime_1",
        file_size=10,
        members=[
            DedupeMemberSnapshot(
                absolute_path="/r1/b.txt",
                relative_path="b.txt",
                scan_root_index=0,
                scan_root_path="/r1",
                mtime_ns=3000,
                size=10,
            ),
            DedupeMemberSnapshot(
                absolute_path="/r0/a.txt",
                relative_path="a.txt",
                scan_root_index=1,
                scan_root_path="/r0",
                mtime_ns=3000,
                size=10,
            ),
            DedupeMemberSnapshot(
                absolute_path="/r2/c.txt",
                relative_path="c.txt",
                scan_root_index=2,
                scan_root_path="/r2",
                mtime_ns=2000,
                size=10,
            ),
        ],
    )

    res = run_advanced_dedupe([group], config)
    g = res.groups[0]
    # Both /r0/a.txt and /r1/b.txt get 60. Deterministic path tie-break chooses /r0/a.txt (lexical order)
    assert g.recommended_keep.absolute_path == "/r0/a.txt"
    assert set(g.quarantine_candidates) == {"/r1/b.txt", "/r2/c.txt"}


def test_mtime_oldest():
    config = validate_and_canonicalize_config({
        "factors": {
            "mtime": {"mode": "oldest", "weight": 60}
        }
    })

    group = DedupeGroupSnapshot(
        provenance_id=6,
        content_hash="hash_mtime_2",
        file_size=10,
        members=[
            DedupeMemberSnapshot(
                absolute_path="/x/new.txt",
                relative_path="new.txt",
                scan_root_index=0,
                scan_root_path="/x",
                mtime_ns=5000,
                size=10,
            ),
            DedupeMemberSnapshot(
                absolute_path="/x/old.txt",
                relative_path="old.txt",
                scan_root_index=0,
                scan_root_path="/x",
                mtime_ns=1000,
                size=10,
            ),
        ],
    )

    res = run_advanced_dedupe([group], config)
    assert res.groups[0].recommended_keep.absolute_path == "/x/old.txt"


# =========================================================================
# 5. Combined Weighted Score & Deterministic Tie-Break
# =========================================================================

def test_combined_weights_and_all_zero():
    # Path priority (50) + Extension (30) + Mtime (20)
    config = validate_and_canonicalize_config({
        "factors": {
            "path_priority": {"enabled": True, "weight": 50, "rules": [{"scope": "absolute", "pattern": "/primary/*"}]},
            "preferred_extension": {"enabled": True, "weight": 30, "extensions": ["jpg"]},
            "mtime": {"mode": "newest", "weight": 20},
        }
    })

    # A: matches path (50) + newest (20) = 70
    # B: matches extension (30) = 30
    group = DedupeGroupSnapshot(
        provenance_id=7,
        content_hash="hash_comb_1",
        file_size=100,
        members=[
            DedupeMemberSnapshot(
                absolute_path="/primary/img.png",
                relative_path="img.png",
                scan_root_index=0,
                scan_root_path="/primary",
                mtime_ns=5000,
                size=100,
            ),
            DedupeMemberSnapshot(
                absolute_path="/secondary/img.jpg",
                relative_path="img.jpg",
                scan_root_index=1,
                scan_root_path="/secondary",
                mtime_ns=1000,
                size=100,
            ),
        ],
    )

    res = run_advanced_dedupe([group], config)
    assert res.groups[0].recommended_keep.absolute_path == "/primary/img.png"
    exp_a = next(m for m in res.groups[0].members if m.absolute_path == "/primary/img.png")
    assert exp_a.total_score == 70

    # All zero config
    zero_config = validate_and_canonicalize_config({})
    res_zero = run_advanced_dedupe([group], zero_config)
    # Both score 0. Lexical tie-break: /primary/img.png < /secondary/img.jpg
    assert res_zero.groups[0].recommended_keep.absolute_path == "/primary/img.png"
    assert res_zero.groups[0].members[0].total_score == 0
    assert res_zero.groups[0].members[1].total_score == 0


# =========================================================================
# 6. Safety Eligibility & Structural Validation
# =========================================================================

def test_safety_ineligible_cannot_activate_rules_or_win():
    config = validate_and_canonicalize_config({
        "factors": {
            "path_priority": {"enabled": True, "weight": 100, "rules": [
                {"scope": "absolute", "pattern": "/ineligible/*"},
                {"scope": "absolute", "pattern": "/backup/*"},
            ]},
            "preferred_extension": {"enabled": True, "weight": 50, "extensions": ["jpg", "png"]},
        }
    })

    # Candidate 1 is in /ineligible and has .jpg, but eligible_as_keep is False!
    # It must NOT activate the first path rule! It must NOT activate .jpg extension!
    group = DedupeGroupSnapshot(
        provenance_id=8,
        content_hash="hash_safety_1",
        file_size=200,
        members=[
            DedupeMemberSnapshot(
                absolute_path="/ineligible/photo.jpg",
                relative_path="photo.jpg",
                scan_root_index=0,
                scan_root_path="/ineligible",
                mtime_ns=9999,
                size=200,
                eligible_as_keep=False,
                safety_reasons=["protected directory last file"],
            ),
            DedupeMemberSnapshot(
                absolute_path="/backup/photo.png",
                relative_path="photo.png",
                scan_root_index=1,
                scan_root_path="/backup",
                mtime_ns=1000,
                size=200,
                eligible_as_keep=True,
            ),
            DedupeMemberSnapshot(
                absolute_path="/other/photo.png",
                relative_path="photo.png",
                scan_root_index=2,
                scan_root_path="/other",
                mtime_ns=1000,
                size=200,
                eligible_as_keep=True,
            ),
        ],
    )

    res = run_advanced_dedupe([group], config)
    g = res.groups[0]
    # The active rule becomes /backup/* because /ineligible/photo.jpg cannot activate rules!
    # /backup/photo.png matches active path rule (100) and .png extension (50) -> 150 score
    assert g.recommended_keep.absolute_path == "/backup/photo.png"
    ineligible_explain = next(m for m in g.members if m.absolute_path == "/ineligible/photo.jpg")
    assert ineligible_explain.eligible_as_keep is False
    assert "protected directory last file" in ineligible_explain.safety_reasons
    assert ineligible_explain.recommended_keep is False


def test_safety_zero_eligible_candidates_skips_group():
    config = validate_and_canonicalize_config({})
    group = DedupeGroupSnapshot(
        provenance_id=9,
        content_hash="hash_all_ineligible",
        file_size=100,
        members=[
            DedupeMemberSnapshot("/a", "a", 0, "/a", 1, 100, eligible_as_keep=False, safety_reasons=["reason1"]),
            DedupeMemberSnapshot("/b", "b", 1, "/b", 1, 100, eligible_as_keep=False, safety_reasons=["reason2"]),
        ],
    )
    res = run_advanced_dedupe([group], config)
    assert res.actionable_group_count == 0
    assert res.skipped_group_count == 1
    assert res.groups[0].status == "skipped"
    assert res.groups[0].skip_reason == "NO_ELIGIBLE_KEEP_CANDIDATE"
    assert len(res.groups[0].quarantine_candidates) == 0


def test_safety_single_eligible_candidate_wins_directly():
    config = validate_and_canonicalize_config({})
    group = DedupeGroupSnapshot(
        provenance_id=10,
        content_hash="hash_one_eligible",
        file_size=100,
        members=[
            DedupeMemberSnapshot("/a", "a", 0, "/a", 1, 100, eligible_as_keep=True),
            DedupeMemberSnapshot("/b", "b", 1, "/b", 1, 100, eligible_as_keep=False, safety_reasons=["quarantine target locked"]),
        ],
    )
    res = run_advanced_dedupe([group], config)
    assert res.actionable_group_count == 1
    assert res.groups[0].status == "actionable"
    assert res.groups[0].recommended_keep.absolute_path == "/a"
    assert res.groups[0].quarantine_candidates == ["/b"]


def test_structural_validation_duplicate_member_path_skips():
    config = validate_and_canonicalize_config({})
    group = DedupeGroupSnapshot(
        provenance_id=11,
        content_hash="hash_duplicate_path",
        file_size=100,
        members=[
            DedupeMemberSnapshot("/same/path.txt", "path.txt", 0, "/same", 1, 100),
            DedupeMemberSnapshot("/same/path.txt", "path.txt", 0, "/same", 1, 100),
        ],
    )
    res = run_advanced_dedupe([group], config)
    assert res.skipped_group_count == 1
    assert res.groups[0].status == "skipped"
    assert res.groups[0].skip_reason == "DUPLICATE_MEMBER_PATH"


def test_structural_validation_size_mismatch_skips():
    config = validate_and_canonicalize_config({})
    group = DedupeGroupSnapshot(
        provenance_id=12,
        content_hash="hash_size_mismatch",
        file_size=100,
        members=[
            DedupeMemberSnapshot("/a.txt", "a.txt", 0, "/", 1, 100),
            DedupeMemberSnapshot("/b.txt", "b.txt", 1, "/", 1, 200),  # size 200 != group.file_size 100
        ],
    )
    res = run_advanced_dedupe([group], config)
    assert res.skipped_group_count == 1
    assert res.groups[0].status == "skipped"
    assert res.groups[0].skip_reason == "MEMBER_SIZE_MISMATCH"


# =========================================================================
# 7. Balanced-by-Bytes Tests
# =========================================================================

def test_balanced_by_bytes_objective():
    # In balanced_by_bytes mode, the balancer chooses among the MAX-SCORE candidates to minimize released bytes spread.
    config = validate_and_canonicalize_config({
        "selection_mode": "balanced_by_bytes",
        "factors": {}  # all zero score, all eligible candidates enter max-score set
    })

    # Group 1: 1000 bytes, roots 0 and 1.
    # Group 2: 500 bytes, roots 0 and 1.
    # Group 1 will be processed first because file_size 1000 > 500.
    g1 = DedupeGroupSnapshot(
        provenance_id=101,
        content_hash="hash_g1",
        file_size=1000,
        members=[
            DedupeMemberSnapshot("/r0/f1.bin", "f1.bin", scan_root_index=0, scan_root_path="/r0", mtime_ns=1, size=1000),
            DedupeMemberSnapshot("/r1/f1.bin", "f1.bin", scan_root_index=1, scan_root_path="/r1", mtime_ns=1, size=1000),
        ],
    )
    g2 = DedupeGroupSnapshot(
        provenance_id=102,
        content_hash="hash_g2",
        file_size=500,
        members=[
            DedupeMemberSnapshot("/r0/f2.bin", "f2.bin", scan_root_index=0, scan_root_path="/r0", mtime_ns=1, size=500),
            DedupeMemberSnapshot("/r1/f2.bin", "f1.bin", scan_root_index=1, scan_root_path="/r1", mtime_ns=1, size=500),
        ],
    )

    # For g1:
    # If keep r0: r1 released = 1000, r0 released = 0. spread = 1000
    # If keep r1: r0 released = 1000, r1 released = 0. spread = 1000
    # Lexical tie break: /r0/f1.bin < /r1/f1.bin -> keep /r0/f1.bin!
    # After g1: released_bytes = {0: 0, 1: 1000}
    #
    # For g2:
    # If keep r0: g2 deletes r1 -> r1 release += 500 -> released = {0: 0, 1: 1500}, spread = 1500
    # If keep r1: g2 deletes r0 -> r0 release += 500 -> released = {0: 500, 1: 1000}, spread = 500
    # Spread 500 < 1500, so balancer MUST choose to keep r1 (/r1/f2.bin)!
    res = run_advanced_dedupe([g1, g2], config, scan_root_indices=[0, 1])
    assert res.groups[0].recommended_keep.absolute_path == "/r0/f1.bin"
    assert res.groups[1].recommended_keep.absolute_path == "/r1/f2.bin"
    assert res.released_bytes_by_scan_root == {0: 500, 1: 1000}


def test_balanced_by_bytes_multiple_copies_in_same_root():
    # If root 0 has 2 copies and root 1 has 1 copy (size 100):
    # Keeping candidate in root 0 deletes the other copy in root 0 (100) + the copy in root 1 (100)
    # -> root 0 released += 100, root 1 released += 100
    # Keeping candidate in root 1 deletes both copies in root 0 (2 * 100 = 200)
    # -> root 0 released += 200, root 1 released += 0
    config = validate_and_canonicalize_config({"selection_mode": "balanced_by_bytes"})
    group = DedupeGroupSnapshot(
        provenance_id=103,
        content_hash="hash_multi_root",
        file_size=100,
        members=[
            DedupeMemberSnapshot("/r0/copy1.txt", "copy1.txt", 0, "/r0", 1, 100),
            DedupeMemberSnapshot("/r0/copy2.txt", "copy2.txt", 0, "/r0", 1, 100),
            DedupeMemberSnapshot("/r1/copy3.txt", "copy3.txt", 1, "/r1", 1, 100),
        ],
    )
    # Prior state: suppose root 0 already released 100 bytes, root 1 released 0 bytes
    # Option A (keep r0 copy1): deletes r0 copy2 (100) and r1 copy3 (100) -> r0 total=200, r1 total=100. spread = 100. sum_sq = 40000 + 10000 = 50000
    # Option B (keep r1 copy3): deletes r0 copy1 (100) and r0 copy2 (100) -> r0 total=300, r1 total=0. spread = 300. sum_sq = 90000
    # Balancer chooses Option A!
    res = run_advanced_dedupe([group], config, scan_root_indices=[0, 1])
    # Both /r0/copy1.txt and /r0/copy2.txt give spread 100. Lexical tie chooses copy1
    assert res.groups[0].recommended_keep.absolute_path == "/r0/copy1.txt"


def test_balanced_by_bytes_cannot_override_higher_score():
    # Crucial rule: Balancer ONLY breaks ties among the max-score candidates!
    # Even if keeping B would produce perfect balance, if A has higher score, A MUST be kept!
    config = validate_and_canonicalize_config({
        "selection_mode": "balanced_by_bytes",
        "factors": {
            "path_priority": {"enabled": True, "weight": 100, "rules": [{"scope": "absolute", "pattern": "/r0/*"}]}
        }
    })

    group = DedupeGroupSnapshot(
        provenance_id=104,
        content_hash="hash_override_check",
        file_size=1000,
        members=[
            DedupeMemberSnapshot("/r0/file.txt", "file.txt", 0, "/r0", 1, 1000),  # score = 100
            DedupeMemberSnapshot("/r1/file.txt", "file.txt", 1, "/r1", 1, 1000),  # score = 0
        ],
    )

    # Even if r1 was heavily behind on balance, r0 wins because of score!
    res = run_advanced_dedupe([group], config, scan_root_indices=[0, 1])
    assert res.groups[0].recommended_keep.absolute_path == "/r0/file.txt"
    assert res.groups[0].members[0].total_score == 100
    assert res.groups[0].members[1].total_score == 0


def test_balanced_by_bytes_includes_zero_release_roots():
    # If roots 0, 1, 2 participate in scan:
    # A decision releases bytes to root 0 and root 1, while root 2 released 0 bytes.
    # Spread MUST be max(released) - min(released) including root 2 (which is 0)!
    config = validate_and_canonicalize_config({"selection_mode": "balanced_by_bytes"})
    group = DedupeGroupSnapshot(
        provenance_id=105,
        content_hash="hash_three_roots",
        file_size=500,
        members=[
            DedupeMemberSnapshot("/r0/f.bin", "f.bin", 0, "/r0", 1, 500),
            DedupeMemberSnapshot("/r1/f.bin", "f.bin", 1, "/r1", 1, 500),
        ],
    )
    res = run_advanced_dedupe([group], config, scan_root_indices=[0, 1, 2])
    assert 2 in res.released_bytes_by_scan_root
    assert res.released_bytes_by_scan_root[2] == 0


# =========================================================================
# 8. Determinism & Fingerprints
# =========================================================================

def test_determinism_member_and_group_order_independence():
    config = validate_and_canonicalize_config({
        "selection_mode": "balanced_by_bytes",
        "factors": {
            "path_priority": {"enabled": True, "weight": 50, "rules": [{"scope": "absolute", "pattern": "*/doc/*"}]},
            "preferred_extension": {"enabled": True, "weight": 30, "extensions": ["pdf", "txt"]},
            "mtime": {"mode": "newest", "weight": 20},
        }
    })

    m1 = DedupeMemberSnapshot("/a/doc/f1.pdf", "doc/f1.pdf", 0, "/a", 1000, 500)
    m2 = DedupeMemberSnapshot("/b/backup/f1.txt", "backup/f1.txt", 1, "/b", 2000, 500)
    g1 = DedupeGroupSnapshot(1, "hash_order_1", 500, [m1, m2])

    m3 = DedupeMemberSnapshot("/x/a.bin", "a.bin", 0, "/x", 500, 1000)
    m4 = DedupeMemberSnapshot("/y/b.bin", "b.bin", 1, "/y", 600, 1000)
    g2 = DedupeGroupSnapshot(2, "hash_order_2", 1000, [m3, m4])

    # Run 1: original order
    res1 = run_advanced_dedupe([g1, g2], config, scan_root_indices=[0, 1])

    # Run 2: reversed group order and reversed member order inside each group
    g1_rev = DedupeGroupSnapshot(1, "hash_order_1", 500, [m2, m1])
    g2_rev = DedupeGroupSnapshot(2, "hash_order_2", 1000, [m4, m3])
    res2 = run_advanced_dedupe([g2_rev, g1_rev], config, scan_root_indices=[0, 1])

    # Must produce byte-identical canonical JSON representation and fingerprints!
    assert res1.actionable_group_count == res2.actionable_group_count
    assert res1.expected_reclaim_bytes == res2.expected_reclaim_bytes
    assert res1.released_bytes_by_scan_root == res2.released_bytes_by_scan_root

    # Group order in result is strictly sorted by (file_size DESC, content_hash ASC, member_path_fingerprint ASC)
    assert [g.recommended_keep.absolute_path for g in res1.groups] == [g.recommended_keep.absolute_path for g in res2.groups]
    assert [g.group_decision_fingerprint for g in res1.groups] == [g.group_decision_fingerprint for g in res2.groups]


# =========================================================================
# 9. Additional Coverage: Oldest Tie, Square Sum Tie Break, Explain & Legacy
# =========================================================================

def test_mtime_oldest_tie():
    config = validate_and_canonicalize_config({
        "factors": {"mtime": {"mode": "oldest", "weight": 50}}
    })
    group = DedupeGroupSnapshot(
        provenance_id=201,
        content_hash="hash_oldest_tie",
        file_size=10,
        members=[
            DedupeMemberSnapshot("/b/file.txt", "file.txt", 0, "/b", mtime_ns=1000, size=10),
            DedupeMemberSnapshot("/a/file.txt", "file.txt", 1, "/a", mtime_ns=1000, size=10),
            DedupeMemberSnapshot("/c/file.txt", "file.txt", 2, "/c", mtime_ns=2000, size=10),
        ],
    )
    res = run_advanced_dedupe([group], config)
    # Both /a and /b tie for oldest with score 50. Lexical tie chooses /a/file.txt
    assert res.groups[0].recommended_keep.absolute_path == "/a/file.txt"


def test_balanced_by_bytes_square_sum_tie_break():
    # 3 roots: 0, 1, 2.
    # Prior state: root 0 has 10 released, root 1 has 0 released, root 2 has 0 released.
    # Group has size 5.
    # Candidate A: if kept, deletes member on root 1 -> root 1 gets +5 -> released = {0: 10, 1: 5, 2: 0}
    #   spread = 10 - 0 = 10. sum_sq = 10^2 + 5^2 + 0^2 = 125.
    # Candidate B: if kept, deletes member on root 0 -> root 0 gets +5 -> released = {0: 15, 1: 0, 2: 0}
    #   spread = 15 - 0 = 15 (spread is worse)
    # What if Candidate C: deletes another on root 0 and root 1:
    # Let's construct two options with identical spread:
    # Suppose prior: root 0 = 10, root 1 = 0, root 2 = 0.
    # Candidate X: releases 10 to root 1 -> {0: 10, 1: 10, 2: 0}. spread = 10 - 0 = 10. sum_sq = 100 + 100 = 200.
    # Candidate Y: releases 5 to root 1 -> {0: 10, 1: 5, 2: 0}. spread = 10 - 0 = 10. sum_sq = 100 + 25 = 125.
    # 125 < 200, so Candidate Y has smaller sum of squares and wins!
    config = validate_and_canonicalize_config({"selection_mode": "balanced_by_bytes"})

    # Setup a group where keeping C_X releases 10 to root 1, and keeping C_Y releases 5 to root 1
    # Group with size 5:
    # 3 members:
    # - C_Y on root 2 (keeping C_Y deletes member on root 1 (size 5) -> root 1 gets +5)
    # - C_X on root 2... wait, group file_size is fixed for all members.
    # If Group 1 has size 10, root 0 has 1 copy, root 1 has 1 copy. Prior releases: {0: 10, 1: 0, 2: 0}.
    # If we evaluate with current_released_bytes = {0: 10, 1: 0, 2: 0}:
    # Opt 1 (keep r1): deletes r0 (10) -> {0: 20, 1: 0, 2: 0}. spread = 20, sum_sq = 400.
    # Opt 2 (keep r0): deletes r1 (10) -> {0: 10, 1: 10, 2: 0}. spread = 10, sum_sq = 200.
    # Opt 2 clearly wins on spread!
    # Now what if Option 1 and Option 2 have SAME spread?
    # e.g. root 0=10, root 1=10, root 2=0.
    # Group size=10, with member on root 0 and member on root 1:
    # Keep r0: deletes r1 -> releases {0: 10, 1: 20, 2: 0}. spread = 20 - 0 = 20. sum_sq = 100 + 400 = 500.
    # Keep r1: deletes r0 -> releases {0: 20, 1: 10, 2: 0}. spread = 20 - 0 = 20. sum_sq = 400 + 100 = 500.
    # (symmetric, tied on sum_sq, lexical tie-break kicks in).
    #
    # To have different sum_sq with same spread:
    # Suppose roots: 0, 1, 2, 3.
    # State A: [10, 5, 5, 0] -> spread = 10 - 0 = 10. sum_sq = 100 + 25 + 25 = 150.
    # State B: [10, 9, 1, 0] -> spread = 10 - 0 = 10. sum_sq = 100 + 81 + 1 = 182.
    # 150 < 182!
    # State A is more evenly distributed and has lower sum_sq!
    from app.planning.dedupe_engine import evaluate_group
    # Test evaluate_group directly with prior state:
    # Prior state: {0: 10, 1: 5, 2: 1, 3: 0}
    # Group size = 4.
    # Member 1 on root 1: keeping it deletes Member 2 on root 2 -> root 2 += 4 -> {0: 10, 1: 5, 2: 5, 3: 0} (spread 10, sum_sq 150)
    # Member 2 on root 2: keeping it deletes Member 1 on root 1 -> root 1 += 4 -> {0: 10, 1: 9, 2: 1, 3: 0} (spread 10, sum_sq 182)
    group = DedupeGroupSnapshot(
        provenance_id=202,
        content_hash="hash_sum_sq",
        file_size=4,
        members=[
            DedupeMemberSnapshot("/z/cand_r1.bin", "cand_r1.bin", 1, "/z", 1, 4),
            DedupeMemberSnapshot("/a/cand_r2.bin", "cand_r2.bin", 2, "/a", 1, 4),
        ],
    )
    # Notice /z/cand_r1.bin has lexical path AFTER /a/cand_r2.bin!
    # If it was lexical tie, /a/cand_r2.bin would win.
    # But because keeping /z/cand_r1.bin produces sum_sq 150 vs 182, /z/cand_r1.bin MUST win on sum_sq!
    res_g = evaluate_group(
        group,
        config,
        current_released_bytes={0: 10, 1: 5, 2: 1, 3: 0},
        all_scan_roots=[0, 1, 2, 3],
    )
    assert res_g.recommended_keep.absolute_path == "/z/cand_r1.bin"
    winner_exp = next(m for m in res_g.members if m.recommended_keep)
    assert winner_exp.selection_reason == "balanced_by_bytes"


def test_explain_balancer_separate_from_score():
    config = validate_and_canonicalize_config({
        "selection_mode": "balanced_by_bytes",
        "factors": {
            "path_priority": {"enabled": True, "weight": 50, "rules": [{"scope": "absolute", "pattern": "/r0/*"}]}
        }
    })
    group = DedupeGroupSnapshot(
        provenance_id=203,
        content_hash="hash_explain_sep",
        file_size=100,
        members=[
            DedupeMemberSnapshot("/r0/f.bin", "f.bin", 0, "/r0", 1, 100),
            DedupeMemberSnapshot("/r1/f.bin", "f.bin", 1, "/r1", 1, 100),
        ],
    )
    res = run_advanced_dedupe([group], config, scan_root_indices=[0, 1])
    winner_explain = next(m for m in res.groups[0].members if m.recommended_keep)

    # Balancer is NOT a score factor!
    factors_in_contrib = [c.factor for c in winner_explain.contributions]
    assert "balanced_by_bytes" not in factors_in_contrib
    assert "balance" not in factors_in_contrib
    assert winner_explain.total_score == 50  # only path_priority (50)


def test_legacy_policies_untouched():
    from collections import Counter
    from app.planning.policies import balanced_score, preference_key, root_rank
    from app.planning.engine import CandidateFile

    # 1. root_rank
    assert root_rank(1, [1, 2, 3]) == 0
    assert root_rank(2, [1, 2, 3]) == 1
    assert root_rank(99, [1, 2, 3]) == 3 + 99

    # 2. balanced_score is delete_counts (file count) based
    c1 = CandidateFile(Path("/r1/f.txt"), root_id=1, top_level_dir="/r1", size=1000, mtime_ns=1, device=1, inode=1)
    c2 = CandidateFile(Path("/r2/f.txt"), root_id=2, top_level_dir="/r2", size=1000, mtime_ns=1, device=1, inode=2)
    members = [c1, c2]

    # delete_counts has 1 delete for root 1, 0 for root 2
    delete_counts = Counter({1: 1, 2: 0})
    # If keeping c1, c2 is deleted -> projected root 2 deletes += 1 -> projected = {1: 1, 2: 1} -> spread = 0
    score_keep_c1 = balanced_score(c1, members, delete_counts, [1, 2])
    # If keeping c2, c1 is deleted -> projected root 1 deletes += 1 -> projected = {1: 2, 2: 0} -> spread = 2
    score_keep_c2 = balanced_score(c2, members, delete_counts, [1, 2])

    assert score_keep_c1[0] == 0  # spread is 0
    assert score_keep_c2[0] == 2  # spread is 2
    assert score_keep_c1 < score_keep_c2

    # 3. preference_key
    assert preference_key(c1, "keep-first-root", [1, 2]) == (0, "/r1/f.txt")
    assert preference_key(c2, "keep-first-root", [1, 2]) == (1, "/r2/f.txt")
    assert preference_key(c1, "keep-newest", [1, 2]) == (-1, 0, "/r1/f.txt")
    assert preference_key(c1, "keep-oldest", [1, 2]) == (1, 0, "/r1/f.txt")

