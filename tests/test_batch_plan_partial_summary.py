from types import SimpleNamespace

from app.worker import _build_incomplete_plan_error_text


def _item(sequence: int, state: str, reason: str | None):
    return SimpleNamespace(
        sequence=sequence,
        operation="quarantine",
        state=state,
        reason=reason,
    )


def test_partial_plan_summary_reports_failures_not_validated_followups():
    text = _build_incomplete_plan_error_text(
        1,
        "partial",
        [
            _item(7, "completed", "completed"),
            _item(
                8,
                "failed",
                "RECURSIVE_PROTECTION_UNSTABLE: protected directory identity changed",
            ),
            _item(9, "validated", "SHA256 verified"),
            _item(10, "validated", "SHA256 verified"),
        ],
    )

    assert "item #8 quarantine: RECURSIVE_PROTECTION_UNSTABLE" in text
    assert "SHA256 verified" not in text
    assert "2 remaining items were not executed after the fail-closed stop" in text


def test_partial_plan_summary_falls_back_when_no_failed_row_exists():
    text = _build_incomplete_plan_error_text(
        2,
        "partial",
        [
            _item(1, "completed", None),
            _item(2, "validated", "SHA256 verified"),
        ],
    )

    assert "item #2 quarantine: SHA256 verified" in text
