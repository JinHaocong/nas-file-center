import React, { useEffect, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useMutation } from '@tanstack/react-query';
import { scansApi } from '../../api/domain';
import type { DedupeDiagnosticResponse } from '../../types/dedupe';
import { formatBytes } from '../../utils/format';
import { CodePath } from '../ui/CodePath';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { useConsoleToast } from '../ui/ConsoleToast';
import { type DedupePairValues, validateDedupePair, toDedupePairPayload } from './diagnostic_form';

interface DedupeDiagnosticModalProps {
  open: boolean;
  onClose: () => void;
  scanJobId?: number | null;
}

const diagnosisCopy: Record<
  DedupeDiagnosticResponse['diagnosis'],
  { title: string; type: 'success' | 'info' | 'warning' | 'error'; detail: string }
> = {
  EXACT_CONTENT_DUPLICATE: {
    title: '当前是两个独立的完全重复副本',
    type: 'success',
    detail: '文件大小和完整 SHA-256 均一致，并且不是同一个 device/inode。',
  },
  SAME_FILESYSTEM_ENTRY: {
    title: '两个路径指向同一个文件系统对象',
    type: 'info',
    detail: 'device/inode 相同，通常是 hardlink 或同一底层对象；不应当作两份独立可释放副本。',
  },
  DIFFERENT_SIZE: {
    title: '文件大小不同',
    type: 'warning',
    detail: '当前文件内容不可能完全一致，NAS File Center 不会把它们作为可执行重复副本。',
  },
  DIFFERENT_CONTENT: {
    title: '完整 SHA-256 不同',
    type: 'warning',
    detail: '当前内容不同，NAS File Center 的执行前校验会拒绝对这对文件做去重隔离。',
  },
  PATH_NOT_FOUND: {
    title: '至少一个路径当前不存在',
    type: 'warning',
    detail: '无法完成当前内容诊断；这也可能解释历史扫描与现在看到的结果不同。',
  },
  PATH_OUTSIDE_CONFIGURED_ROOTS: {
    title: '路径不在配置的安全根目录内',
    type: 'error',
    detail: '诊断不会读取白名单之外的文件。',
  },
  SYMLINK_UNSUPPORTED: {
    title: '检测到符号链接',
    type: 'warning',
    detail: '重复诊断和去重执行都不会把符号链接当作普通副本处理。',
  },
  NOT_REGULAR_FILE: {
    title: '至少一个路径不是普通文件',
    type: 'warning',
    detail: '目录或特殊文件不会进入普通重复文件处理链。',
  },
  INDETERMINATE: {
    title: '当前无法确定',
    type: 'warning',
    detail: '文件在读取哈希时发生变化或读取失败，请在文件稳定后重新诊断。',
  },
};

const reasonCopy: Record<string, string> = {
  PATH_OUTSIDE_SCAN_ROOTS: '不在该扫描的根目录内',
  QUARANTINE_EXCLUDED: '属于隔离区，扫描会排除',
  SYMLINK_EXCLUDED: '符号链接被排除',
  NON_REGULAR_FILE_EXCLUDED: '不是普通文件',
  NOT_IN_SNAPSHOT_FILTER_OR_SCAN_TIME_STATE: '未进入当时快照；扫描过滤条件或扫描时文件状态可能是原因',
  NOT_IN_SNAPSHOT_AT_SCAN_TIME: '当前路径没有出现在该扫描的重复快照中',
};


const DiagnosticPath: React.FC<{
  label: string;
  item: DedupeDiagnosticResponse['paths'][number];
}> = ({ label, item }) => {
  const toast = useConsoleToast();
  const copyHash = async () => {
    if (!item.sha256) return;
    try {
      await navigator.clipboard.writeText(item.sha256);
      toast.success('SHA-256 已复制');
    } catch {
      toast.error('无法复制 SHA-256，请手动选中复制');
    }
  };
  return (
    <section className="nfc-dedupe-diagnostic-path nfc-v2-diagnostic-path">
      <div className="nfc-dedupe-diagnostic-path-heading">
        <strong>{label}</strong>
        {item.in_quarantine && <span className="nfc-v2-diagnostic-tag">隔离区</span>}
        {item.is_symlink && <span className="nfc-v2-diagnostic-tag is-warning">symlink</span>}
      </div>
      <CodePath value={item.requested_path} />
      <dl className="nfc-v2-diagnostic-facts">
        <div><dt>存在</dt><dd>{item.exists ? '是' : '否'}</dd></div>
        <div><dt>普通文件</dt><dd>{item.is_regular_file ? '是' : '否'}</dd></div>
        <div><dt>大小</dt><dd>{item.size == null ? '—' : formatBytes(item.size)}</dd></div>
        <div><dt>Device / Inode</dt><dd className="nfc-mono">
          {item.device == null || item.inode == null ? '—' : item.device + ' / ' + item.inode}
        </dd></div>
        <div><dt>mtime_ns</dt><dd className="nfc-mono">{item.mtime_ns ?? '—'}</dd></div>
        <div className="is-wide"><dt>SHA-256</dt><dd className="nfc-v2-diagnostic-hash">
          <span className="nfc-mono">{item.sha256 || item.hash_error || '—'}</span>
          {item.sha256 && (
            <button type="button" aria-label={'复制' + label + ' SHA-256'} onClick={() => { void copyHash(); }}>
              <ConsoleIcon name="file-check" size={15} /> 复制
            </button>
          )}
        </dd></div>
      </dl>
    </section>
  );
};

export const DedupeDiagnosticModal: React.FC<DedupeDiagnosticModalProps> = ({
  open, onClose, scanJobId = null,
}) => {
  const [values, setValues] = useState<DedupePairValues>({ pathA: '', pathB: '' });
  const [validationError, setValidationError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const toast = useConsoleToast();

  const mutation = useMutation({
    mutationFn: (request: ReturnType<typeof toDedupePairPayload>) =>
      scansApi.diagnosePair(request),
    onError: (err: Error) => toast.error(err.message || '重复诊断失败'),
    onSettled: () => { inFlight.current = false; },
  });

  useEffect(() => {
    if (!open) return;
    setValues({ pathA: '', pathB: '' });
    setValidationError(null);
    inFlight.current = false;
    mutation.reset();
    // Only reset on open or scan context change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, scanJobId]);

  const busy = mutation.isPending;
  const close = () => {
    if (busy || inFlight.current) return;
    onClose();
  };
  const update = (key: keyof DedupePairValues, value: string) => {
    setValues(previous => ({ ...previous, [key]: value }));
    setValidationError(null);
    if (!busy) mutation.reset(); // Results never describe edited paths.
  };
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || inFlight.current) return;
    const failure = validateDedupePair(values);
    if (failure) {
      setValidationError(failure);
      return;
    }
    inFlight.current = true;
    setValidationError(null);
    mutation.mutate(toDedupePairPayload(values, scanJobId));
  };

  const result = mutation.data;
  const diagnosis = result ? diagnosisCopy[result.diagnosis] : null;

  return (
    <Dialog.Root open={open} onOpenChange={next => { if (!next) close(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-dedupe-overlay" />
        <Dialog.Content className="nfc-overlay-modal nfc-dedupe-diagnostic-modal nfc-v2-dedupe-dialog nfc-v2-diagnostic-dialog"
          onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}>
          <header className="nfc-v2-dedupe-dialog-header">
            <div>
              <Dialog.Title>重复文件诊断</Dialog.Title>
              <Dialog.Description>
                {scanJobId
                  ? '比较当前内容并解释 Scan #' + scanJobId + ' 快照中的状态。'
                  : '比较当前内容和文件系统身份。'}
              </Dialog.Description>
            </div>
            <button type="button" className="nfc-v2-dedupe-close"
              aria-label="关闭重复诊断" disabled={busy} onClick={close}>
              <ConsoleIcon name="x" size={18} />
            </button>
          </header>
          <div className="nfc-dedupe-diagnostic-stack nfc-v2-diagnostic-stack">
            <div className="nfc-v2-dedupe-note" role="note">
              <ConsoleIcon name="shield-check" size={18} />
              只读诊断，不会移动、隔离或删除文件；所有文件路径受服务端 ALLOWED_ROOTS / PathGuard 限制。
            </div>
            <form className="nfc-v2-dedupe-form" onSubmit={submit}>
              <div className="nfc-v2-dedupe-field">
                <label htmlFor="nfc-diagnostic-path-a">文件 A</label>
                <input id="nfc-diagnostic-path-a" required type="text" placeholder="/data/..."
                  value={values.pathA} disabled={busy}
                  onChange={event => update('pathA', event.target.value)} />
              </div>
              <div className="nfc-v2-dedupe-field">
                <label htmlFor="nfc-diagnostic-path-b">文件 B</label>
                <input id="nfc-diagnostic-path-b" required type="text" placeholder="/data/..."
                  value={values.pathB} disabled={busy}
                  onChange={event => update('pathB', event.target.value)} />
              </div>
              {validationError && <div className="nfc-v2-dedupe-error" role="alert">{validationError}</div>}
              <div className="nfc-v2-dedupe-actions is-leading">
                <ConsoleButton type="submit" variant="primary" loading={busy}
                  leadingIcon={<ConsoleIcon name="search" size={16} />}>开始诊断</ConsoleButton>
                {result && (
                  <ConsoleButton disabled={busy} onClick={() => mutation.reset()}>清除结果</ConsoleButton>
                )}
              </div>
            </form>
            {result && diagnosis && (
              <section className="nfc-dedupe-diagnostic-result" aria-label="诊断结果">
                <div className={'nfc-v2-diagnostic-summary is-' + diagnosis.type} role="status">
                  <strong>{diagnosis.title}</strong>
                  <span>{diagnosis.detail}</span>
                </div>
                <div className="nfc-dedupe-diagnostic-path-grid">
                  <DiagnosticPath label="文件 A" item={result.paths[0]} />
                  <DiagnosticPath label="文件 B" item={result.paths[1]} />
                </div>
                <dl className="nfc-v2-diagnostic-comparison">
                  <div><dt>同一 inode</dt><dd>{result.same_filesystem_entry ? '是' : '否'}</dd></div>
                  <div><dt>大小一致</dt><dd>
                    {result.size_match == null ? '未知' : result.size_match ? '是' : '否'}
                  </dd></div>
                  <div><dt>SHA-256 一致</dt><dd>
                    {result.sha256_match == null ? '未知' : result.sha256_match ? '是' : '否'}
                  </dd></div>
                </dl>
                {result.scan && (
                  <section className="nfc-dedupe-diagnostic-scan">
                    <div className="nfc-dedupe-diagnostic-section-heading">
                      <div>
                        <strong>Scan #{result.scan.scan_job_id} 快照解释</strong>
                        <span>{result.scan.name}</span>
                      </div>
                      <span className="nfc-v2-diagnostic-tag">
                        {result.scan.same_duplicate_group ? '当时属于同一重复组' : '当时未记录为同一重复组'}
                      </span>
                    </div>
                    <div className="nfc-dedupe-diagnostic-scan-grid">
                      {result.scan.paths.map((pathInfo, index) => (
                        <div key={index} className="nfc-dedupe-diagnostic-scan-path">
                          <strong>文件 {index === 0 ? 'A' : 'B'}</strong>
                          <span>快照成员：{pathInfo.included_in_duplicate_snapshot ? '是' : '否'}</span>
                          <span>Scan Root：{pathInfo.scan_root_index == null ? '—' : '#' + pathInfo.scan_root_index}</span>
                          {pathInfo.memberships.length > 0 && (
                            <span>Group：{pathInfo.memberships.map(entry => '#' + entry.group_id).join(', ')}</span>
                          )}
                          {pathInfo.reasons.map(reason => (
                            <span className="nfc-warning-text" key={reason}>
                              {reasonCopy[reason] || reason}
                            </span>
                          ))}
                        </div>
                      ))}
                    </div>
                    <div className="nfc-dedupe-diagnostic-filter-note">
                      <span>当时参数</span>
                      <span>min-size: {result.scan.fclones_args.min_size || '无'}</span>
                      <span>match-links: {result.scan.fclones_args.match_links ? '开启' : '关闭'}</span>
                      <span>include patterns: {result.scan.fclones_args.name_patterns?.join(', ') || '无'}</span>
                      <span>exclude patterns: {result.scan.fclones_args.exclude_patterns?.join(', ') || '无'}</span>
                    </div>
                  </section>
                )}
              </section>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
