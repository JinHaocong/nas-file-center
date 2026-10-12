import React, { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { CodePath } from '../../components/ui/CodePath';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { getPaginationState } from '../../components/ui/paginationModel';
import { useTitle } from '../../hooks/useTitle';
import { directoryDiffApi } from '../../api/domain';
import type { DirectoryDiffResponse, DirectoryDiffRow } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import {
  type DirectoryDiffFilterMode, applyDirectoryDiffVerification,
  buildDirectoryDiffRequest, buildDirectoryDiffVerifyRequest, buildDirectoryDiffCsv,
  directoryDiffRowLabel, directoryDiffTone, filterDirectoryDiffRows, formatDirectoryDiffSize,
} from '../../utils/directoryDiffSafety';

function exportCsv(rows: readonly DirectoryDiffRow[]): void {
  const csv = buildDirectoryDiffCsv(rows);
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'nas-directory-diff.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Only Preview and explicit on-demand SHA256; no filesystem mutation or Plan creation. */
export const DirectoryDiffPage: React.FC = () => {
  useTitle('双目录差异对比');
  const toast = useConsoleToast();
  const [rootA, setRootA] = useState('');
  const [rootB, setRootB] = useState('');
  const [result, setResult] = useState<DirectoryDiffResponse | null>(null);
  const [filter, setFilter] = useState<DirectoryDiffFilterMode>('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [verifyingPath, setVerifyingPath] = useState<string | null>(null);
  const activePreviewKey = useRef<string | null>(null);
  const requestTicket = useRef(0);
  const previewGuard = useRef(false);
  const verifyGuard = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activePreviewKey.current = null;
      requestTicket.current += 1;
    };
  }, []);

  const clearResult = () => {
    // Unique ticket also rejects the ABA case of editing A -> B -> A while a request is pending.
    requestTicket.current += 1;
    activePreviewKey.current = null;
    setResult(null);
    setFilter('all');
    setPage(1);
  };
  const patchRoot = (which: 'a' | 'b', value: string) => {
    if (which === 'a') setRootA(value);
    else setRootB(value);
    clearResult();
  };

  const previewMutation = useMutation({ mutationFn: directoryDiffApi.preview });
  const verifyMutation = useMutation({ mutationFn: directoryDiffApi.verify });

  const runPreview = async () => {
    if (previewGuard.current) return;
    const input = buildDirectoryDiffRequest(rootA, rootB);
    if (!input) {
      toast.error(!rootA.trim() || !rootB.trim()
        ? '请选择需要对比的 A 和 B 目录' : 'A 与 B 必须选择不同目录');
      return;
    }
    clearResult();
    const ticket = requestTicket.current;
    const requestKey = JSON.stringify(input);
    activePreviewKey.current = requestKey;
    previewGuard.current = true;
    setPreviewLoading(true);
    try {
      const report = await previewMutation.mutateAsync(input);
      if (!mountedRef.current || requestTicket.current !== ticket ||
          activePreviewKey.current !== requestKey) return;
      setResult(report);
      // All SHA256 calls must use the canonical server paths, never text assembled in UI.
      activePreviewKey.current = JSON.stringify({ root_a: report.root_a, root_b: report.root_b });
      toast.success('只读对比完成，列出 ' + report.total + ' 个路径');
    } catch (error: unknown) {
      if (mountedRef.current && requestTicket.current === ticket &&
          activePreviewKey.current === requestKey) {
        clearResult();
        toast.error(getStructuredApiError(error).message || '目录对比失败');
      }
    } finally {
      previewGuard.current = false;
      if (mountedRef.current) setPreviewLoading(false);
    }
  };

  const verifyRow = async (row: DirectoryDiffRow) => {
    if (verifyGuard.current || previewGuard.current || previewLoading || !result) return;
    const request = buildDirectoryDiffVerifyRequest(result, row);
    const key = JSON.stringify({ root_a: result.root_a, root_b: result.root_b });
    if (!request || activePreviewKey.current !== key) return;
    const ticket = requestTicket.current;
    verifyGuard.current = true;
    setVerifyingPath(request.relative_path);
    try {
      const response = await verifyMutation.mutateAsync(request);
      if (!mountedRef.current || requestTicket.current !== ticket ||
          activePreviewKey.current !== key) return;
      const updated = applyDirectoryDiffVerification(result, request, response);
      if (!updated) {
        toast.error('校验响应与当前路径不匹配，请重新对比');
        return;
      }
      setResult(current => current ? applyDirectoryDiffVerification(current, request, response) || current : current);
      toast.info(response.same_content ? 'SHA256 一致：内容相同' : 'SHA256 不一致：内容不同');
    } catch (error: unknown) {
      if (mountedRef.current && requestTicket.current === ticket &&
          activePreviewKey.current === key) {
        toast.error(getStructuredApiError(error).message || '精确校验失败，请重新对比');
      }
    } finally {
      verifyGuard.current = false;
      if (mountedRef.current) setVerifyingPath(null);
    }
  };

  const visible = filterDirectoryDiffRows(result?.items || [], filter);
  const pages = getPaginationState(page, pageSize, visible.length);
  const visiblePage = visible.slice((pages.current - 1) * pageSize, pages.current * pageSize);

  const badge = (row: DirectoryDiffRow) => (
    <span className={'nfc-v2-directory-diff-tag tone-' + directoryDiffTone(row)}>
      {directoryDiffRowLabel(row)}
    </span>
  );
  const canVerify = (row: DirectoryDiffRow) => result !== null &&
    activePreviewKey.current === JSON.stringify({ root_a: result.root_a, root_b: result.root_b }) &&
    !!buildDirectoryDiffVerifyRequest(result, row);
  const verifyAction = (row: DirectoryDiffRow) => canVerify(row) ? (
    <ConsoleButton size="sm" loading={verifyingPath === row.relative_path}
      disabled={previewLoading || verifyingPath !== null}
      leadingIcon={<ConsoleIcon name="shield-check" size={15} />}
      aria-label={'SHA256 校验 ' + row.relative_path}
      onClick={() => { void verifyRow(row); }}>SHA256</ConsoleButton>
  ) : <span className="nfc-v2-directory-diff-muted">—</span>;

  return (
    <div className="nfc-operations-page nfc-directory-diff-page nfc-page-layout-workbench nfc-v2-directory-diff">
      <PageHeader title="双目录差异对比"
        description="按相对路径递归比较两个目录，完全只读；大小相同不代表内容相同，必要时可单项 SHA256 核验。" />
      <DataPanel title="选择对比目录"
        description="只读取两个互不包含的目录树；排除隔离区及符号链接，单侧最多扫描 10,000 个文件/目录条目。"
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench">
        <div className="nfc-v2-directory-diff-form">
          <div className="nfc-form-grid">
            <div className="nfc-v2-directory-diff-field" role="group" aria-label="目录 A">
              <span>目录 A</span>
              <DirectoryPicker value={rootA} placeholder="选择待对比的 A 目录"
                onChange={value => patchRoot('a', typeof value === 'string' ? value : value[0] || '')} />
            </div>
            <div className="nfc-v2-directory-diff-field" role="group" aria-label="目录 B">
              <span>目录 B</span>
              <DirectoryPicker value={rootB} placeholder="选择待对比的 B 目录"
                onChange={value => patchRoot('b', typeof value === 'string' ? value : value[0] || '')} />
            </div>
          </div>
          <ActionBar className="nfc-file-tool-primary-actions">
            <ConsoleButton variant="primary" loading={previewLoading}
              leadingIcon={<ConsoleIcon name="git-compare" size={17} />}
              onClick={() => { void runPreview(); }}>生成只读差异</ConsoleButton>
          </ActionBar>
        </div>
      </DataPanel>
      <div className="nfc-v2-directory-diff-notice nfc-page-alert" role="note">
        <ConsoleIcon name="info" size={19} />
        <div><strong>V1 不做自动同步或任何文件修改</strong>
          <p>目录均存在仅表示相对目录名存在，并不意味着目录内文件相同。
            大小相同的文件需要 SHA256 校验才能确认内容一致；单文件校验上限 256 MiB。</p>
        </div>
      </div>
      {result && (
        <DataPanel title="目录差异结果" variant="dense"
          className="nfc-panel-flush nfc-file-tool-result-panel"
          description={'A：' + result.entries_a + ' 项；B：' + result.entries_b +
            ' 项；排除符号链接 A ' + result.skipped_symlinks_a +
            ' / B ' + result.skipped_symlinks_b + ' 个'}
          action={<span className="nfc-panel-count">{visible.length} / {result.total} 路径</span>}>
          <div className="nfc-form-grid nfc-v2-directory-diff-roots">
            <div><strong>目录 A</strong><CodePath value={result.root_a} /></div>
            <div><strong>目录 B</strong><CodePath value={result.root_b} /></div>
          </div>
          <ActionBar className="nfc-v2-directory-diff-actions">
            <label className="nfc-v2-directory-diff-filter">
              <span>筛选结果</span>
              <select value={filter}
                onChange={event => { setFilter(event.target.value as DirectoryDiffFilterMode); setPage(1); }}>
                <option value="all">全部路径</option>
                <option value="differences">明确差异</option>
                <option value="unverified">大小相同待校验</option>
                <option value="verified">已做 SHA256 校验</option>
                <option value="only_a">仅 A 存在</option>
                <option value="only_b">仅 B 存在</option>
                <option value="size_different">大小不同</option>
                <option value="type_mismatch">文件类型不同</option>
              </select>
            </label>
            <ConsoleButton disabled={!visible.length}
              leadingIcon={<ConsoleIcon name="arrow-down" size={17} />}
              onClick={() => exportCsv(visible)}>
              导出当前筛选 CSV（{visible.length} 项）
            </ConsoleButton>
          </ActionBar>
          {visible.length === 0 ? (
            <ConsoleEmpty title="当前筛选没有对应文件或目录"
              description="可以调整筛选，或修改目录重新生成只读差异。" />
          ) : (
            <ResponsiveDataView
              desktop={
                <div className="nfc-v2-directory-diff-table-scroll">
                  <table className="nfc-v2-directory-diff-table">
                    <caption>目录差异与单项 SHA256 校验结果</caption>
                    <thead><tr>
                      <th scope="col">相对路径</th>
                      <th scope="col">A 类型</th>
                      <th scope="col">B 类型</th>
                      <th scope="col">A 大小</th>
                      <th scope="col">B 大小</th>
                      <th scope="col">结果</th>
                      <th scope="col">校验</th>
                    </tr></thead>
                    <tbody>{visiblePage.map(row => (
                      <tr key={row.relative_path}>
                        <td><CodePath value={row.relative_path} /></td>
                        <td>{row.kind_a === 'file' ? '文件' : row.kind_a === 'directory' ? '目录' : '—'}</td>
                        <td>{row.kind_b === 'file' ? '文件' : row.kind_b === 'directory' ? '目录' : '—'}</td>
                        <td>{formatDirectoryDiffSize(row.size_a)}</td>
                        <td>{formatDirectoryDiffSize(row.size_b)}</td>
                        <td>{badge(row)}</td>
                        <td>{verifyAction(row)}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              }
              mobile={
                <div className="nfc-mobile-record-list nfc-v2-directory-diff-mobile">
                  {visiblePage.map(row => (
                    <article className="nfc-mobile-record-card" key={row.relative_path}>
                      <div className="nfc-mobile-record-heading">
                        {badge(row)}
                        {verifyAction(row)}
                      </div>
                      <CodePath value={row.relative_path} />
                      <div className="nfc-mobile-record-facts">
                        <span>A：{formatDirectoryDiffSize(row.size_a)} ({row.kind_a || '缺失'})</span>
                        <span>B：{formatDirectoryDiffSize(row.size_b)} ({row.kind_b || '缺失'})</span>
                      </div>
                    </article>
                  ))}
                </div>
              }
            />
          )}
          <ConsolePagination page={pages.current} pageSize={pageSize} total={visible.length}
            pageSizes={[10, 20, 30, 50, 100]}
            onChange={(nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize); }} />
        </DataPanel>
      )}
    </div>
  );
};
