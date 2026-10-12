import React, { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { plansApi } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import { useTitle } from '../../hooks/useTitle';
import { splitLines } from '../../utils/format';
import { type BatchOperation, buildBatchDraft } from '../../utils/batchDraftSafety';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

const operations: readonly { op: BatchOperation; title: string; detail: string }[] = [
  { op: 'quarantine', title: '批量隔离', detail: 'Quarantine' },
  { op: 'touch', title: '更新时间戳', detail: 'Touch' },
  { op: 'move', title: '批量移动', detail: 'Move' },
  { op: 'rename', title: '批量改名', detail: 'Rename' },
];

/** Only create a Plan Draft, never Freeze/Validate/Execute a filesystem operation. */
export const BatchPage: React.FC = () => {
  useTitle('批量处理');
  const navigate = useNavigate();
  const toast = useConsoleToast();
  const [name, setName] = useState('批量处理');
  const [operation, setOperation] = useState<BatchOperation>('quarantine');
  const [paths, setPaths] = useState<string[]>([]);
  const [mappingsText, setMappingsText] = useState('');
  const [planLoading, setPlanLoading] = useState(false);
  const [validationError, setValidationError] = useState('');
  const mountedRef = useRef(true);
  const planGuard = useRef(false);
  const planMutation = useMutation({ mutationFn: plansApi.createPlan });

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const handleGeneratePlan = async () => {
    if (planGuard.current) return;
    const { draft, error } = buildBatchDraft(name, operation, paths, mappingsText);
    if (!draft) {
      const message = error || '请检查计划内容';
      setValidationError(message);
      toast.error(message);
      return;
    }
    setValidationError('');
    planGuard.current = true;
    setPlanLoading(true);
    try {
      const created = await planMutation.mutateAsync(draft);
      if (!mountedRef.current) return;
      toast.success('已生成批量处理计划 #' + created.id + '，仍需冻结与校验');
      navigate('/plans/' + created.id);
    } catch (error: unknown) {
      if (mountedRef.current) {
        toast.error(getStructuredApiError(error).message || '生成计划失败');
      }
    } finally {
      planGuard.current = false;
      if (mountedRef.current) setPlanLoading(false);
    }
  };

  const onOperationChange = (next: BatchOperation) => {
    if (planGuard.current) return;
    setOperation(next);
    setValidationError('');
  };
  const onPathsChange = (next: string | string[]) => {
    if (planGuard.current) return;
    setPaths(Array.isArray(next) ? [...next] : splitLines(next));
    setValidationError('');
  };

  return (
    <div className="nfc-operations-page nfc-batch-page nfc-page-layout-workbench nfc-v2-batch">
      <PageHeader title="批量文件处理"
        description="批量隔离、Touch、Move 与 Rename 统一先创建 Plan；真正文件操作仍通过 Freeze → Validate → Execute。" />
      <DataPanel title="批量操作定义"
        description="选择操作类型并明确输入源路径/映射。这里创建 Plan，不会立即执行文件系统变更。"
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench">
        <div className="nfc-batch-form nfc-v2-batch-form">
          <label className="nfc-v2-batch-field">
            <span>计划名称</span>
            <input value={name} required disabled={planLoading}
              placeholder="批量处理计划" aria-invalid={Boolean(validationError) && !name.trim()}
              onChange={event => { setName(event.target.value); setValidationError(''); }} />
          </label>
          <fieldset className="nfc-v2-batch-operations">
            <legend>操作类型</legend>
            <div className="nfc-batch-operation-grid">
              {operations.map(item => (
                <label key={item.op} className={'nfc-v2-batch-radio' +
                  (operation === item.op ? ' is-selected' : '')}>
                  <input type="radio" name="batch-operation" value={item.op}
                    checked={operation === item.op} disabled={planLoading}
                    onChange={() => onOperationChange(item.op)} />
                  <span>{item.title}<small>{item.detail}</small></span>
                </label>
              ))}
              <label className="nfc-v2-batch-radio is-disabled">
                <input type="radio" value="hardlink" disabled />
                <span>硬链接去重<small>未实现</small></span>
              </label>
              <label className="nfc-v2-batch-radio is-disabled">
                <input type="radio" value="reflink" disabled />
                <span>Reflink 浅克隆<small>未实现</small></span>
              </label>
            </div>
          </fieldset>
          {operation === 'quarantine' && (
            <div className="nfc-v2-batch-notice nfc-page-alert" role="note">
              <ConsoleIcon name="shield-check" size={19} />
              <div><strong>Quarantine-first 隔离</strong>
                <p>文件移动到 NAS File Center 隔离区并保留原目录结构；不会直接永久删除。</p>
              </div>
            </div>
          )}
          {(operation === 'quarantine' || operation === 'touch') && (
            <div className="nfc-v2-batch-field" role="group" aria-label="文件或目录绝对路径清单">
              <span>文件或目录绝对路径清单</span>
              <DirectoryPicker multiple value={paths} disabled={planLoading}
                placeholder="点击选择或添加目录或路径..."
                onChange={onPathsChange} />
              <small>支持可视化选择目录；单文件路径可通过高级手动输入填写。</small>
            </div>
          )}
          {(operation === 'move' || operation === 'rename') && (
            <label className="nfc-v2-batch-field">
              <span>路径映射清单</span>
              <textarea rows={7} className="nfc-mono-input" disabled={planLoading}
                value={mappingsText}
                placeholder={'/data/DiskA/file1.txt -> /data/DiskB/file1.txt\n/data/DiskA/file2.txt -> /data/DiskB/file2.txt'}
                onChange={event => { setMappingsText(event.target.value); setValidationError(''); }} />
              <small>每行一条：源路径 -&gt; 目标路径；均需填写绝对路径。</small>
            </label>
          )}
          {validationError && <p className="nfc-v2-batch-error" role="alert">{validationError}</p>}
          <ActionBar className="nfc-file-tool-primary-actions">
            <ConsoleButton variant="primary" loading={planLoading}
              leadingIcon={<ConsoleIcon name="calendar" size={17} />}
              onClick={() => { void handleGeneratePlan(); }}>
              生成批量处理 Plan
            </ConsoleButton>
            <span className="nfc-form-note">
              Plan 创建后仍需在计划详情完成 Freeze、Validate 与 Execute。
            </span>
          </ActionBar>
        </div>
      </DataPanel>
    </div>
  );
};
