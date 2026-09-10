import pytest
from datetime import datetime, timezone
import zoneinfo
from app.resource_control import (
    ResourcePolicySnapshot,
    EffectiveResourcePolicy,
    ResourcePolicyValidationError,
    ResourcePolicyConfigError,
    resource_policy_row_fingerprint,
    validate_resource_policy_snapshot,
    evaluate_resource_policy,
    parse_positive_thread_ceiling,
    compose_fclones_thread_cap,
    is_resource_controlled_job,
    resolve_timezone,
)
from app.models import ResourcePolicy

def test_default_policy_evaluation_returns_full_profile():
    snap = ResourcePolicySnapshot(
        scan_threads=2,
        hash_threads=2,
        io_limit="normal",
        job_priority="normal",
        active_window_enabled=False,
        active_window_start=None,
        active_window_end=None,
        active_window_timezone=None,
        outside_window_mode="limited",
        revision=1,
    )
    validate_resource_policy_snapshot(snap)
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    eff = evaluate_resource_policy(snap, now_utc=now)
    assert eff.profile == "full"
    assert eff.inside_active_window is None
    assert eff.resource_jobs_admitted is True
    assert eff.effective_thread_cap == 2
    assert eff.revision == 1

def test_resource_policy_row_fingerprint():
    row = ResourcePolicy(
        id=1,
        scan_threads=2,
        hash_threads=4,
        io_limit="normal",
        job_priority="background",
        active_window_enabled=True,
        active_window_start="01:00",
        active_window_end="07:00",
        active_window_timezone="UTC",
        outside_window_mode="pause",
        revision=3,
    )
    fp = resource_policy_row_fingerprint(row)
    assert fp == (3, 2, 4, "normal", "background", True, "01:00", "07:00", "UTC", "pause")
    assert resource_policy_row_fingerprint(None) is None

def test_active_window_same_day_boundaries():
    snap = ResourcePolicySnapshot(
        4,
        4,
        "normal",
        "normal",
        True,
        "08:00",
        "18:00",
        "UTC",
        "pause",
        1,
    )

    start = evaluate_resource_policy(
        snap,
        now_utc=datetime(
            2026, 9, 10, 8, 0,
            tzinfo=timezone.utc,
        ),
    )
    assert start.inside_active_window is True
    assert start.profile == "full"
    assert start.resource_jobs_admitted is True

    before_end = evaluate_resource_policy(
        snap,
        now_utc=datetime(
            2026, 9, 10, 17, 59,
            tzinfo=timezone.utc,
        ),
    )
    assert before_end.profile == "full"

    exact_end = evaluate_resource_policy(
        snap,
        now_utc=datetime(
            2026, 9, 10, 18, 0,
            tzinfo=timezone.utc,
        ),
    )
    assert exact_end.inside_active_window is False
    assert exact_end.profile == "pause"
    assert exact_end.resource_jobs_admitted is False

def test_active_window_cross_midnight():
    snap = ResourcePolicySnapshot(
        4,
        4,
        "normal",
        "normal",
        True,
        "23:00",
        "07:00",
        "UTC",
        "limited",
        1,
    )

    before_midnight = evaluate_resource_policy(
        snap,
        now_utc=datetime(
            2026, 9, 10, 23, 30,
            tzinfo=timezone.utc,
        ),
    )
    assert before_midnight.profile == "full"

    after_midnight = evaluate_resource_policy(
        snap,
        now_utc=datetime(
            2026, 9, 11, 6, 59,
            tzinfo=timezone.utc,
        ),
    )
    assert after_midnight.profile == "full"

    exact_end = evaluate_resource_policy(
        snap,
        now_utc=datetime(
            2026, 9, 11, 7, 0,
            tzinfo=timezone.utc,
        ),
    )
    assert exact_end.inside_active_window is False
    assert exact_end.profile == "limited"
    assert exact_end.effective_thread_cap == 1

    daytime_outside = evaluate_resource_policy(
        snap,
        now_utc=datetime(
            2026, 9, 11, 12, 0,
            tzinfo=timezone.utc,
        ),
    )
    assert daytime_outside.profile == "limited"
    assert daytime_outside.effective_thread_cap == 1

def test_evaluate_resource_policy_with_pre_resolved_timezone():
    snap = ResourcePolicySnapshot(4, 4, "normal", "normal", True, "08:00", "18:00", "Asia/Shanghai", "pause", 1)
    tz = resolve_timezone("Asia/Shanghai")
    # 09:00 UTC is 17:00 Shanghai -> inside [08:00, 18:00)
    now_in = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)
    eff_in = evaluate_resource_policy(snap, now_utc=now_in, resolved_timezone=tz)
    assert eff_in.profile == "full"
    assert eff_in.resource_jobs_admitted is True

    # 11:00 UTC is 19:00 Shanghai -> outside
    now_out = datetime(2026, 9, 10, 11, 0, tzinfo=timezone.utc)
    eff_out = evaluate_resource_policy(snap, now_utc=now_out, resolved_timezone=tz)
    assert eff_out.profile == "pause"
    assert eff_out.resource_jobs_admitted is False

def test_io_limit_calculations():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # low limits cap to 1, profile is full
    snap_low = ResourcePolicySnapshot(4, 4, "low", "normal", False, None, None, None, "limited", 1)
    eff_low = evaluate_resource_policy(snap_low, now_utc=now)
    assert eff_low.profile == "full"
    assert eff_low.effective_thread_cap == 1

    # normal limits cap to 2 even if threads configured to 8
    snap_norm = ResourcePolicySnapshot(8, 8, "normal", "normal", False, None, None, None, "limited", 1)
    assert evaluate_resource_policy(snap_norm, now_utc=now).effective_thread_cap == 2

    # unlimited uses min(scan, hash)
    snap_unlim = ResourcePolicySnapshot(8, 6, "unlimited", "normal", False, None, None, None, "limited", 1)
    assert evaluate_resource_policy(snap_unlim, now_utc=now).effective_thread_cap == 6

def test_strict_validation_rejects_malformed_inputs():
    with pytest.raises(ResourcePolicyValidationError):
        validate_resource_policy_snapshot(ResourcePolicySnapshot(True, 2, "normal", "normal", False, None, None, None, "limited", 1))
    with pytest.raises(ResourcePolicyValidationError):
        validate_resource_policy_snapshot(ResourcePolicySnapshot(2, 2, "normal", "normal", True, "08:00", "08:00", "UTC", "limited", 1))
    with pytest.raises(ResourcePolicyValidationError):
        validate_resource_policy_snapshot(ResourcePolicySnapshot(2, 2, "normal", "normal", True, "08:00", "18:00", "Mars/Phobos", "limited", 1))

def test_compose_fclones_thread_cap():
    assert compose_fclones_thread_cap(2, None, None) == 2
    assert compose_fclones_thread_cap(2, "1", None) == 1
    assert compose_fclones_thread_cap(2, "8", None) == 2
    assert compose_fclones_thread_cap(6, 4, 3) == 3
    with pytest.raises(ResourcePolicyConfigError):
        compose_fclones_thread_cap(2, "invalid_threads", None)

def test_is_resource_controlled_job():
    assert is_resource_controlled_job("index-root") is True
    assert is_resource_controlled_job("fclones-scan") is True
    assert is_resource_controlled_job("batch-plan-execute") is False
    assert is_resource_controlled_job("quarantine-apply") is False

def test_disabled_active_window_allows_equal_valid_times():
    snap = ResourcePolicySnapshot(
        scan_threads=2,
        hash_threads=2,
        io_limit="normal",
        job_priority="normal",
        active_window_enabled=False,
        active_window_start="08:00",
        active_window_end="08:00",
        active_window_timezone="UTC",
        outside_window_mode="pause",
        revision=1,
    )

    validate_resource_policy_snapshot(snap)

    eff = evaluate_resource_policy(
        snap,
        now_utc=datetime(
            2026,
            9,
            10,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert eff.profile == "full"
    assert eff.inside_active_window is None
    assert eff.resource_jobs_admitted is True
    assert eff.effective_thread_cap == 2

def test_disabled_active_window_still_rejects_malformed_non_null_time():
    snap = ResourcePolicySnapshot(
        2,
        2,
        "normal",
        "normal",
        False,
        "99:99",
        "08:00",
        "UTC",
        "limited",
        1,
    )

    with pytest.raises(ResourcePolicyValidationError):
        validate_resource_policy_snapshot(snap)
