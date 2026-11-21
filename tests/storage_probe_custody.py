"""Explicit tmp-path-only custody for storage probe algorithm tests.

This is not a production issuer or a proof that host/NAS writers are excluded.
Tests exercising real admission refusal must not request this fixture.
"""
from pathlib import Path

import pytest

from app.batch.media_organizer_custody import NamespaceCustodyUnavailable
from app.storage_optimization import capability


@pytest.fixture
def scoped_probe_namespace(tmp_path, monkeypatch):
    state = {"allowed": True, "proofs": []}

    class SyntheticProof:
        def __init__(self, identities):
            self.identities = dict(identities)
            self.closed = False

        def assert_exclusive(self, parent):
            if self.closed or not state["allowed"]:
                raise NamespaceCustodyUnavailable("synthetic probe custody revoked")
            assert isinstance(parent, Path) and parent.is_relative_to(tmp_path)
            assert parent in self.identities
            observed = parent.stat()
            assert (observed.st_dev, observed.st_ino) == self.identities[parent]

        def close(self):
            self.closed = True

    def issue(identities):
        proof = SyntheticProof(identities)
        for parent in identities:
            proof.assert_exclusive(parent)
        state["proofs"].append(proof)
        return proof

    # raising=False also permits the RED test against the unguarded baseline.
    monkeypatch.setattr(capability, "verified_probe_namespace_custody", issue, raising=False)
    return state
