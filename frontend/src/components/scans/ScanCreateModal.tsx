import React, { useEffect, useState } from 'react';
import { Modal } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { scansApi } from '../../api/domain';
import { DirectoryPicker } from '../DirectoryPicker';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { useConsoleToast } from '../ui/ConsoleToast';
import {
  type ScanCreateValues, validateScanCreateValues, toScanCreatePayload,
} from './scan_create';

interface Props { open: boolean; onClose: () => void; }

const emptyValues = (): ScanCreateValues => ({
  name: 'Scan-' + new Date().toISOString().slice(0, 10),
  roots: [],
  isolate: false,
  minSize: '',
  namePatternsText: '',
  excludePatternsText: '',
});

/**
 * Native form controls, retaining the proven directory picker and its Ant
 * overlay until DirectoryPickerModal is independently migrated.
 */
export const ScanCreateModal: React.FC<Props> = ({ open, onClose }) => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const toast = useConsoleToast();
  const [values, setValues] = useState<ScanCreateValues>(emptyValues);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setValues(emptyValues());
      setValidationError(null);
    }
  }, [open]);

  const createMutation = useMutation({
    mutationFn: (request: ReturnType<typeof toScanCreatePayload>) =>
      scansApi.createScan(request),
    onSuccess: res => {
      toast.success('扫描任务已加入后台队列');
      setValues(emptyValues());
      setValidationError(null);
      onClose();
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      queryClient.invalidateQueries({ queryKey: ['workJobsList'] });
      navigate('/scans/' + res.scan_job_id);
    },
    onError: (err: Error) => {
      const message = err.message || '创建扫描失败';
      setValidationError(message);
      toast.error(message);
    },
  });

  const close = () => {
    if (createMutation.isPending) return;
    setValidationError(null);
    onClose();
  };

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (createMutation.isPending) return;
    const failure = validateScanCreateValues(values);
    if (failure) {
      setValidationError(failure);
      return;
    }
    setValidationError(null);
    createMutation.mutate(toScanCreatePayload(values));
  };

  const update = <K extends keyof ScanCreateValues>(key: K, value: ScanCreateValues[K]) => {
    setValues(current => ({ ...current, [key]: value }));
    setValidationError(null);
  };

  return (
    <Modal
      title="新建 fclones 精确扫描任务"
      open={open}
      onCancel={close}
      footer={null}
      width={640}
      closable={!createMutation.isPending}
      keyboard={!createMutation.isPending}
      maskClosable={!createMutation.isPending}
      destroyOnClose
      className="nfc-form-modal nfc-overlay-modal nfc-scan-create-modal nfc-v2-scan-create-modal"
    >
      <form className="nfc-v2-scan-create-form" onSubmit={submit}>
        <div className="nfc-v2-scan-create-field">
          <label htmlFor="nfc-scan-name">任务名称</label>
          <input id="nfc-scan-name" type="text" required
            autoComplete="off" placeholder="例如：电影库与备份盘跨盘查重"
            value={values.name} disabled={createMutation.isPending}
            onChange={event => update('name', event.target.value)} />
        </div>

        <div className="nfc-v2-scan-create-field">
          <span className="nfc-v2-scan-create-label" id="nfc-scan-roots-label">
            待扫描根目录
          </span>
          <DirectoryPicker multiple disabled={createMutation.isPending}
            value={values.roots}
            onChange={next => update('roots', Array.isArray(next)
              ? next.map(String) : String(next || '').split('\n').map(v => v.trim()).filter(Boolean))}
            placeholder="点击选择或添加待扫描目录..." />
          <p className="nfc-v2-scan-create-hint">请至少选择一个目录；所有路径必须位于 ALLOWED_ROOTS 白名单内。</p>
        </div>

        <label className="nfc-v2-scan-create-switch">
          <input type="checkbox" checked={values.isolate}
            disabled={createMutation.isPending}
            onChange={event => update('isolate', event.target.checked)} />
          <span>
            <strong>跨目录隔离模式 (Isolate / A-B)</strong>
            <small>仅报告跨越不同输入根目录的重复组，不报告单根目录内部重复。</small>
          </span>
        </label>

        <div className="nfc-v2-scan-create-field">
          <label htmlFor="nfc-scan-min-size">最小文件大小过滤</label>
          <input id="nfc-scan-min-size" type="text"
            placeholder="例如：100M、1G；留空不限制"
            value={values.minSize} disabled={createMutation.isPending}
            onChange={event => update('minSize', event.target.value)} />
        </div>

        <div className="nfc-v2-scan-create-patterns">
          <div className="nfc-v2-scan-create-field">
            <label htmlFor="nfc-scan-include">包含文件名 Pattern（每行一个，可选）</label>
            <textarea id="nfc-scan-include" rows={3} placeholder={'*.mp4\n*.mkv'}
              value={values.namePatternsText} disabled={createMutation.isPending}
              onChange={event => update('namePatternsText', event.target.value)} />
          </div>
          <div className="nfc-v2-scan-create-field">
            <label htmlFor="nfc-scan-exclude">排除文件名 Pattern（每行一个，可选）</label>
            <textarea id="nfc-scan-exclude" rows={3} placeholder={'*.part\n*.tmp'}
              value={values.excludePatternsText} disabled={createMutation.isPending}
              onChange={event => update('excludePatternsText', event.target.value)} />
          </div>
        </div>

        {validationError && (
          <div className="nfc-v2-scan-create-error" role="alert">{validationError}</div>
        )}
        <div className="nfc-v2-scan-create-note">
          <ConsoleIcon name="shield-check" size={16} />
          扫描仅读取目录并生成结果快照；后续文件修改需要单独的 Plan 安全流程。
        </div>
        <div className="nfc-v2-scan-create-actions">
          <ConsoleButton disabled={createMutation.isPending} onClick={close}>取消</ConsoleButton>
          <ConsoleButton type="submit" variant="primary" loading={createMutation.isPending}
            leadingIcon={<ConsoleIcon name="file-search" size={16} />}>开始扫描</ConsoleButton>
        </div>
      </form>
    </Modal>
  );
};
