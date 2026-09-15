from __future__ import annotations

import json
import sys
import types

from . import handlers_base as _impl


# Keep the existing handler implementation byte-for-byte intact in
# handlers_base.py. Re-export its public/private module surface so existing
# imports remain compatible, then wrap only batch-plan terminal bookkeeping for
# the new Gate6-A2 operation.
for _name, _value in vars(_impl).items():
    if not _name.startswith("__"):
        globals()[_name] = _value


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


class _HandlerCompatibilityModule(types.ModuleType):
    """Preserve the historical app.tasks.handlers patch seam.

    Handler classes still execute with handlers_base.py as their defining
    module, so tests and callers that patch app.tasks.handlers.run_scan,
    safe_quarantine_hash, execute_item, or other re-exported implementation
    globals must update the defining module too. This keeps the Gate6-A2
    bookkeeping wrapper transparent to all pre-existing handler behavior.
    """

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name != "_impl" and hasattr(_impl, name):
            setattr(_impl, name, value)


sys.modules[__name__].__class__ = _HandlerCompatibilityModule
