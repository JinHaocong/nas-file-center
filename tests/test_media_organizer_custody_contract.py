"""Custody assertions must raise on denial and return only None on success."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.batch.media_organizer_custody import (
    NamespaceCustodyUnavailable,
    assert_exclusive_custody,
    verified_namespace_custody,
)


@pytest.mark.parametrize(
    "result",
    [True, False, 1, 0, "approved", "", {"exclusive": True}, {}, []],
    ids=["true", "false", "one", "zero", "text", "empty-text",
         "record", "empty-record", "empty-list"],
)
def test_non_none_assertion_result_never_authorizes_custody(tmp_path, result):
    # A provider with the right method name must not convert a Boolean or
    # unchecked evidence record into permission to cross a mutation fence.
    proof = SimpleNamespace(assert_exclusive=lambda parent: result)

    with pytest.raises(NamespaceCustodyUnavailable, match="custody"):
        assert_exclusive_custody(proof, (tmp_path,))


def test_none_result_requires_each_requested_parent_to_be_asserted(tmp_path):
    parents = (tmp_path, tmp_path / "source", tmp_path / "public")
    checked = []

    class ScopedProof:
        def assert_exclusive(self, parent: Path) -> None:
            if parent not in parents:
                raise NamespaceCustodyUnavailable("outside custody scope")
            checked.append(parent)

    assert assert_exclusive_custody(ScopedProof(), parents) is None
    assert checked == list(parents)


def test_live_issuer_remains_unavailable_even_with_all_execution_flags(tmp_path):
    settings = SimpleNamespace(
        media_organizer_execution_enabled=True,
        media_organizer_namespace_quiescence_ack=True,
        allow_mutation=True,
        allow_delete=True,
    )

    with pytest.raises(NamespaceCustodyUnavailable, match="not proven"):
        verified_namespace_custody(settings, tmp_path)
