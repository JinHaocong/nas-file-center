import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { schedulerApi } from '../../api/scheduler';
import type { ScheduleItem, ScheduleRun } from '../../types/scheduler';
import { formatDateTime } from '../../utils/format';
import { ConsoleSheet } from '../../components/ui/ConsoleSheet';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';

interface Props { schedule: ScheduleItem | null; onClose: () => void; }

const runStatusClass = (status: ScheduleRun['status']) =>
  status === 'dispatched' ? 'is-dispatched' :
  status === 'failed' ? 'is-failed' :
  status === 'skipped_overlap' ? 'is-skipped' : 'is-pending';

export const ScheduleHistoryDrawer: React.FC<Props> = ({ schedule, onClose }) => {
  const navigate = useNavigate();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['schedule-runs', schedule?.id],
    queryFn: () => schedulerApi.listRuns(schedule!.id, 100),
    enabled: Boolean(schedule), refetchInterval: schedule ? 5000 : false,
  });
  return (
    <ConsoleSheet open={Boolean(schedule)} onClose={onClose}
      title={schedule ? schedule.name + ' · 运行历史' : '运行历史'}
      description="持久运行记录、版本快照及 Task 跳转"
      eyebrow="RUN HISTORY" className="nfc-scheduler-history-drawer nfc-v2-scheduler-history">
      {isLoading ? (
        <div className="nfc-scheduler-history-loading" role="status">正在读取运行记录…</div>
      ) : isError ? (
        <div className="nfc-v2-scheduler-note" role="alert">
          <span>加载运行历史失败</span>
          <ConsoleButton size="sm" onClick={() => { void refetch(); }}>重试</ConsoleButton>
        </div>
      ) : !data?.items?.length ? (
        <ConsoleEmpty title="暂无运行记录" description="触发后会在这里记录调度结果。" />
      ) : (
        <div className="nfc-scheduler-run-list">
          {data.items.map(run => (
            <article key={run.id} className="nfc-scheduler-run-card">
              <div className="nfc-scheduler-run-heading">
                <strong>Run #{run.id}</strong>
                <span className={'nfc-v2-scheduler-run-state ' + runStatusClass(run.status)}>
                  {run.status}
                </span>
              </div>
              <div className="nfc-scheduler-run-facts">
                <span>触发：{formatDateTime(run.scheduled_for_utc)}</span>
                <span>Schedule revision：r{run.schedule_revision}</span>
                {run.work_job_id && (
                  <ConsoleButton size="sm" variant="ghost"
                    leadingIcon={<ConsoleIcon name="arrow-right" size={15} />}
                    onClick={() => navigate('/tasks?task=' + run.work_job_id)}>
                    Task #{run.work_job_id} · {run.work_job_status || 'unknown'}
                  </ConsoleButton>
                )}
              </div>
              {(run.error_code || run.error_text) && (
                <div className="nfc-v2-scheduler-note is-warning" role="note">
                  <ConsoleIcon name="info" size={17} />
                  <div><strong>{run.error_code || '运行未派发'}</strong>
                    {run.error_text && <p>{run.error_text}</p>}
                  </div>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </ConsoleSheet>
  );
};
