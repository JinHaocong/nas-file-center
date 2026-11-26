import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleCheckbox } from '../../components/ui/ConsoleCheckbox';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { DataPanel } from '../../components/ui/DataPanel';

import { getStructuredApiError } from '../../api/errors';
import { mediaOrganizerBatchApi, type OrganizerJobId } from '../../api/mediaOrganizerBatch';

import { formatBytes } from '../../utils/format';

type PackageMode = 'existing' | 'new';

const fileTypes = { P: '图片', V: '视频', Other: '其他' };
const pageSizes = [25, 50, 100];

/** A new package name must be a single unreserved directory name. */
function isPackageName(name: string): boolean {
  return Boolean(name) && name === name.trim() && name !== '.' && name !== '..' &&
    !/[\\/\x00-\x1f]/u.test(name) && !name.toLowerCase().startsWith('.nfc-');
}

/** Review one author's actual loose files and draft their selected same-author moves. */
export function MediaOrganizerLooseFilesReport({
  previewId, looseId, author, disabled, onClose, onDraftBusyChange, onDraftCreated, planId,
}: {
  previewId: OrganizerJobId;
  looseId: string;
  author: string;
  disabled: boolean;
  onClose: () => void;
  onDraftBusyChange: (busy: boolean) => void;
  onDraftCreated: (planId: string) => void;
  planId?: string;
}) {
  const [pagination, setPagination] = useState({ page: 1, size: 50 });
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [mode, setMode] = useState<PackageMode>('existing');
  const [existingPackage, setExistingPackage] = useState('');
  const [newPackage, setNewPackage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState('');
  const submittingRef = useRef(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const { data, error, isError } = useQuery({
    queryKey: ['mediaOrganizerLooseFiles', previewId, looseId, pagination.page, pagination.size],
    queryFn: () => mediaOrganizerBatchApi.getLooseFiles(previewId, looseId, pagination.page, pagination.size),
  });
  const createPackage = data?.packages.length === 0 || mode === 'new';
  const formDisabled = disabled || submitting;

  useEffect(() => {
    panelRef.current?.focus({ preventScroll: true });
    panelRef.current?.scrollIntoView?.({ block: 'start' });
  }, []);

  /** Keep checked source paths when switching between pages of the same author. */
  function selectSource(source: string, checked: boolean) {
    setSelected(previous => {
      const next = new Set(previous);
      if (checked) next.add(source);
      else next.delete(source);
      return next;
    });
  }

  /** Submit once and keep the preview available while the resulting draft is linked. */
  async function submitDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!data || formDisabled || submittingRef.current || selected.size === 0) return;
    const packageName = createPackage ? newPackage : existingPackage;
    if (createPackage && !isPackageName(packageName)) {
      setProblem('请输入合法的资源包目录名。');
      return;
    }
    if (!createPackage && !data.packages.includes(packageName)) {
      setProblem('请选择同一作者的现有资源包。');
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    onDraftBusyChange(true);
    setProblem('');
    try {
      const draft = await mediaOrganizerBatchApi.createAssignmentDraft(previewId, looseId, {
        sources: [...selected], package_name: packageName, new_package: createPackage,
      });
      onDraftCreated(draft.plan_id);
      setSelected(new Set());
    } catch (error: unknown) {
      setProblem(getStructuredApiError(error).message || '无法生成归属草稿');
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
      onDraftBusyChange(false);
    }
  }

  return (
    <div ref={panelRef} tabIndex={-1} aria-label="作者层待归属散件" role="region">
      <DataPanel title="作者层待归属散件" variant="dense" className="nfc-v2-batch-media-panel"
        description={<CodePath value={author} />}
        action={<ConsoleButton size="sm" variant="ghost" disabled={submitting} onClick={onClose}>关闭</ConsoleButton>}>
        {isError ? (
          <p className="nfc-v2-batch-error" role="alert">{getStructuredApiError(error).message || '无法读取散件清单'}</p>
        ) : !data ? <p role="status">正在读取散件清单…</p> : (
          <form className="nfc-v2-batch-form" onSubmit={submitDraft}>
            <p className="nfc-form-note" aria-live="polite">
              已选 {selected.size.toLocaleString()} / {data.total_files.toLocaleString()} 件，可跨页勾选。
            </p>
            {data.packages.length > 0 && (
              <label className="nfc-v2-batch-field">
                归属方式
                <select value={mode} disabled={formDisabled} onChange={event => {
                  setMode(event.target.value === 'new' ? 'new' : 'existing');
                  setProblem('');
                }}>
                  <option value="existing">归入现有资源包</option>
                  <option value="new">新建资源包</option>
                </select>
              </label>
            )}
            {createPackage ? (
              <label className="nfc-v2-batch-field">
                新资源包名称
                <input id="media-organizer-new-package" type="text" value={newPackage} maxLength={255}
                  disabled={formDisabled} onChange={event => { setNewPackage(event.target.value); setProblem(''); }} />
              </label>
            ) : (
              <label className="nfc-v2-batch-field">
                同作者资源包
                <select id="media-organizer-existing-package" value={existingPackage} disabled={formDisabled}
                  onChange={event => { setExistingPackage(event.target.value); setProblem(''); }}>
                  <option value="">请选择</option>
                  {data.packages.map(name => <option key={name} value={name}>{name}</option>)}
                </select>
              </label>
            )}
            <div className="nfc-file-tool-primary-actions">
              <ConsoleButton type="submit" variant="primary" loading={submitting}
                disabled={formDisabled || selected.size === 0 || !(createPackage ? newPackage : existingPackage)}>
                生成归属草稿
              </ConsoleButton>
            </div>
            {problem && <p className="nfc-v2-batch-error" role="alert">{problem}</p>}
            {planId && (
              <p className="nfc-form-note" role="status">
                已生成归属草稿。<Link to={`/plans/${encodeURIComponent(planId)}`}>查看草稿</Link>
              </p>
            )}
            {data.files.length === 0 ? <ConsoleEmpty title="这一页没有散件" /> : (
              <div className="nfc-v2-batch-media-scroll">
                <table className="nfc-v2-batch-media-table">
                  <caption className="nfc-v2-batch-media-sr-only">作者层直属文件</caption>
                  <thead><tr><th scope="col">选择</th><th scope="col">源路径</th>
                    <th scope="col">类型</th><th scope="col">大小</th></tr></thead>
                  <tbody>{data.files.map(file => (
                    <tr key={file.source}>
                      <td><ConsoleCheckbox aria-label={`选择 ${file.source}`} checked={selected.has(file.source)}
                        disabled={formDisabled} onCheckedChange={checked => selectSource(file.source, checked)} /></td>
                      <td><CodePath value={file.source} /></td>
                      <td>{fileTypes[file.kind]}</td>
                      <td>{formatBytes(file.bytes)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            <ConsolePagination page={pagination.page} pageSize={pagination.size} total={data.total_files}
              pageSizes={pageSizes} onChange={(page, size) => setPagination({ page, size })} />
          </form>
        )}
      </DataPanel>
    </div>
  );
}
