from __future__ import annotations

import json

from . import handlers_base as _impl


# Keep the existing handler implementation byte-for-byte intact in
# handlers_base.py.  Re-export its public/private module surface so existing
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
