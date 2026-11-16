import React, { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { media_packageApi } from '../../api/media_package';
import { getStructuredApiError } from '../../api/errors';
import { useConsoleToast } from '../ui/ConsoleToast';
import { ConsoleButton } from '../ui/ConsoleButton';

interface Props {
  failedJobId: number;
  onViewTask?: (taskId: number) => void;
}

/** Explicit, single-use recovery. Never silently reruns a failed file move. */
export const MediaPackageRecoveryPanel: React.FC<Props> = ({
  failedJobId, onViewTask,
}) => {
  const toast = useConsoleToast();
  const [confirmation, setConfirmation] = useState('');
  const [recoveryJobId, setRecoveryJobId] = useState<number | null>(null);
  const token = `RECOVER_MEDIA_PACKAGE_EXECUTION_${failedJobId}`;
  const recover = useMutation({
    mutationFn: () => media_packageApi.recoverExecution(failedJobId, confirmation),
  });

  const start = async () => {
    if (confirmation !== token || recover.isPending || recoveryJobId !== null) return;
    try {
      const next = await recover.mutateAsync();
      setRecoveryJobId(next.job_id);
      setConfirmation('');
      toast.success(`安全恢复任务 #${next.job_id} 已加入队列`);
    } catch (error: unknown) {
      toast.error(getStructuredApiError(error).message || '恢复前安全检查未通过');
    }
  };

  return (
    <section className="nfc-overlay-section" aria-label="媒体资源包冻结清单安全恢复">
      <header className="nfc-overlay-section-header">
        <div><span>Frozen manifest</span><h3>安全恢复原执行任务</h3></div>
      </header>
      <div className="nfc-v2-task-inline-alert">
        <strong>原任务保留，不允许普通重试或重新扫描后直接执行。</strong>
        <p>仅对发布前目录标识误判开放恢复。服务端会重新验证原冻结清单、
          文件身份、暂存内容及目标路径，出现任何异常立即拒绝。</p>
        <p>恢复会继续实际移动文件，请先检查 NAS 上的原任务、数据与磁盘状态；
          不要删除隐藏暂存目录。</p>
      </div>
      {recoveryJobId !== null ? (
        <div role="status">
          <p>已创建安全恢复任务 #{recoveryJobId}。原失败任务 #{failedJobId} 保留审计。</p>
          {onViewTask && (
            <ConsoleButton variant="secondary" size="sm"
              onClick={() => onViewTask(recoveryJobId)}>
              查看恢复任务
            </ConsoleButton>
          )}
        </div>
      ) : (
        <div className="nfc-v2-batch-form">
          <p>确认码（须完整输入）：<code>{token}</code></p>
          <label htmlFor={`media-package-recovery-${failedJobId}`}>恢复确认码</label>
          <input id={`media-package-recovery-${failedJobId}`}
            type="text" autoComplete="off" spellCheck={false}
            value={confirmation} onChange={e => setConfirmation(e.target.value)}
            placeholder="完整输入恢复确认码" />
          <ConsoleButton variant="danger" loading={recover.isPending}
            disabled={confirmation !== token || recover.isPending}
            onClick={() => { void start(); }}>
            校验原清单并创建恢复任务
          </ConsoleButton>
        </div>
      )}
    </section>
  );
};
