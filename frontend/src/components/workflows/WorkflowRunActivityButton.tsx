import { useEffect, useId, useRef, useState } from 'react';

import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { ConsoleSheet } from '../ui/ConsoleSheet';
import { ProgressMotionTrack } from '../ui/ProgressMotionTrack';

import {
  useWorkflowRunActivity, workflowRunActive, workflowRunDirectoryName, workflowRunStage,
} from './WorkflowRunActivity';
import { WorkflowRunReceiptBody, WorkflowRunReceiptFooter, workflowRunPercent } from './WorkflowRunReceipt';

/** Reopen the same receipt from the header or the mobile task dock. */
export function WorkflowRunActivityButton({ compact = false }: { compact?: boolean }) {
  const runs = useWorkflowRunActivity()?.runs ?? [];
  const [expanded, setExpanded] = useState(false);
  const [openJobId, setOpenJobId] = useState<string | null>(null);
  const area = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const popupId = useId();
  const count = runs.filter(workflowRunActive).length;
  const top = runs.find(workflowRunActive) ?? runs[0];
  const opened = runs.find(run => run.receipt.jobId === openJobId)?.receipt;

  useEffect(() => {
    if (!expanded) return;
    function onPointerDown(event: PointerEvent) {
      if (event.target instanceof Node && !area.current?.contains(event.target)) setExpanded(false);
    }
    function onEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      event.preventDefault();
      setExpanded(false);
      trigger.current?.focus({ preventScroll: true });
    }
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onEscape);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onEscape);
    };
  }, [expanded]);

  if (!top) return null;
  const value = workflowRunPercent(top);
  const directory = workflowRunDirectoryName(top.receipt.directory);
  const label = top.error ? '读取异常' : value === null || !workflowRunActive(top) ? workflowRunStage(top) : value + '%';
  const close = () => setOpenJobId(null);

  return <div className={'nfc-run-activity' + (compact ? ' is-compact' : '')} ref={area}>
    <button type="button" className="nfc-run-activity-trigger" ref={trigger}
      aria-label={'后台任务 · ' + directory + ' · ' + label}
      aria-controls={expanded ? popupId : undefined} aria-expanded={expanded}
      onClick={() => setExpanded(value => !value)} title={directory + ' · ' + label}>
      <ConsoleIcon name="workflow" size={16} />
      <span className="nfc-run-activity-name">{directory}</span>
      <strong>{label}</strong>
      <ConsoleIcon name="chevron-down" className="nfc-run-activity-chevron" size={13} />
    </button>
    {expanded && <section className="nfc-run-activity-popover" id={popupId} aria-label="后台任务">
      <header><strong>后台任务</strong><span>{count ? count + ' 个进行中' : '本次会话'}</span></header>
      <ul>
        {runs.map(run => {
          const percent = workflowRunPercent(run);
          const stage = run.error ? '进度读取异常' : workflowRunStage(run);
          const active = workflowRunActive(run);
          return <li key={run.receipt.jobId} className="nfc-run-activity-row" data-active={active || undefined}>
            <span className="nfc-run-receipt-icon"><ConsoleIcon name={active ? 'workflow' : 'history'} size={18} /></span>
            <div className="nfc-run-activity-entry">
              <div><strong title={run.receipt.directory}>{workflowRunDirectoryName(run.receipt.directory)}</strong>
                {active && percent !== null && <b className="nfc-run-percent">{percent}%</b>}</div>
              <small>{run.receipt.workflowName} · {stage}</small>
              {active && percent !== null && <ProgressMotionTrack value={percent}>
                <progress max={100} value={percent} aria-label="任务完成进度">{percent}%</progress>
              </ProgressMotionTrack>}
              <ConsoleButton size="sm" onClick={() => {
                trigger.current?.focus({ preventScroll: true });
                setExpanded(false);
                setOpenJobId(run.receipt.jobId);
              }} leadingIcon={<ConsoleIcon name="arrow-right" size={14} />}>查看进度</ConsoleButton>
            </div>
          </li>;
        })}
      </ul>
    </section>}
    {opened && <ConsoleSheet open onClose={close} title="运行工作流" description="本次目录与执行进度"
      className="nfc-workflow-quick-run nfc-workflow-run-receipt" returnFocusFallback={() => trigger.current}
      footer={<WorkflowRunReceiptFooter receipt={opened} onClose={close} />}>
      <WorkflowRunReceiptBody receipt={opened} />
    </ConsoleSheet>}
  </div>;
}
