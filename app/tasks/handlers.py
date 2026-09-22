from __future__ import annotations

import json
import sys
import types

from sqlalchemy import event

from . import handlers_base as _impl
from .utility_structural_cleanup_compat import (
    normalize_structural_cleanup_journal,
    reconcile_utility_structural_cleanup,
)
from app.media.corrupt_delete import reconcile_corrupt_media_delete


# Keep the existing handler implementation byte-for-byte intact in
# handlers_base.py. Re-export its public/private module surface so existing
# imports remain compatible, then wrap only narrowly frozen compatibility
# behavior around the defining module.
for _name, _value in vars(_impl).items():
    if not _name.startswith("__"):
        globals()[_name] = _value


if not getattr(_impl._reconcile_executing_item, "_gate6b_structural_cleanup_wrapped", False):
    _original_reconcile_executing_item = _impl._reconcile_executing_item

    def _gate6b_reconcile_executing_item(
        session,
        item,
        plan_id,
        job_id,
        user_id,
        settings,
        now,
        **kwargs,
    ):
        if reconcile_corrupt_media_delete(
            session,
            item,
            plan_id,
            job_id,
            user_id,
            settings,
            now,
            **kwargs,
        ):
            return
        if reconcile_utility_structural_cleanup(
            session,
            item,
            plan_id,
            job_id,
            user_id,
            settings,
            now,
        ):
            return
        return _original_reconcile_executing_item(
            session,
            item,
            plan_id,
            job_id,
            user_id,
            settings,
            now,
            **kwargs,
        )

    _gate6b_reconcile_executing_item._gate6b_structural_cleanup_wrapped = True
    _impl._reconcile_executing_item = _gate6b_reconcile_executing_item
    _reconcile_executing_item = _gate6b_reconcile_executing_item


if not getattr(_impl.OperationJournal, "_gate6b_structural_cleanup_listener", False):
    def _gate6b_structural_cleanup_before_insert(mapper, connection, target):
        normalize_structural_cleanup_journal(connection, target)

    event.listen(
        _impl.OperationJournal,
        "before_insert",
        _gate6b_structural_cleanup_before_insert,
    )
    _impl.OperationJournal._gate6b_structural_cleanup_listener = True


if not getattr(_impl.BatchPlanExecuteHandler.run, "_gate6a2_terminal_wrapped", False):
    _original_batch_plan_execute_run = _impl.BatchPlanExecuteHandler.run

    def _gate6a2_terminal_run(self, job, context, settings):
        _original_batch_plan_execute_run(self, job, context, settings)

        state = json.loads(job.state_json or "{}")
        plan_id = int(state.get("plan_id", 0))
        if not plan_id:
            return

        from app.quarantine.bulk_unlink_terminal import (
            finalize_bulk_unlink_terminal_audits,
        )

        finalize_bulk_unlink_terminal_audits(
            context.SessionLocal,
            plan_id=plan_id,
            task_id=int(job.id),
            worker_id=getattr(context, "worker_id", None),
        )

    _gate6a2_terminal_run._gate6a2_terminal_wrapped = True
    _impl.BatchPlanExecuteHandler.run = _gate6a2_terminal_run


BatchPlanExecuteHandler = _impl.BatchPlanExecuteHandler

# Gate6-D registers media-analysis and SHA256 integrity verification handlers
# on the canonical handler registry.
from app.media.handler import MediaAnalysisHandler as MediaAnalysisHandler
from app.media.integrity_handler import MediaIntegrityVerifyHandler as MediaIntegrityVerifyHandler


class _HandlerCompatibilityModule(types.ModuleType):
    """Preserve the historical app.tasks.handlers patch seam.

    Handler classes still execute with handlers_base.py as their defining
    module, so tests and callers that patch app.tasks.handlers.run_scan,
    safe_quarantine_hash, execute_item, or other re-exported implementation
    globals must update the defining module too. This keeps the compatibility
    wrappers transparent to all pre-existing handler behavior.
    """

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name != "_impl" and hasattr(_impl, name):
            setattr(_impl, name, value)


sys.modules[__name__].__class__ = _HandlerCompatibilityModule
