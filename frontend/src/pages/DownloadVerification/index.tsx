import React, { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { useTitle } from '../../hooks/useTitle';
import { downloadVerificationApi } from '../../api/downloadVerification';
import { getStructuredApiError } from '../../api/errors';

const verdict: Record<string, string> = {
  VERIFIED_IDENTICAL: '完整校验一致',
  DIFFERENT: '发现差异',
  INCOMPLETE: '尚未完成或不可验证',
  STALE: '校验期间目录发生变化',
  VERIFIED_MATCH: 'SHA256 一致',
  HASH_MISMATCH: 'SHA256 不一致',
  ONLY_LOCAL: '仅 NAS 存在',
  ONLY_REMOTE: '仅 PikPak 存在',
  SIZE_MISMATCH: '文件大小不同',
  TYPE_MISMATCH: '条目类型不同',
  DIRECTORY_MATCH: '目录一致',
};

export const DownloadVerificationPage: React.FC = () => {
  useTitle('下载完整性校验');
  const [remoteRoot, setRemoteRoot] = useState('');
  const [localRoot, setLocalRoot] = useState('');
  const [selected, setSelected] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState('');

  const config = useQuery({ queryKey: ['download-verify-config'], queryFn: downloadVerificationApi.configuration });
  const runs = useQuery({
    queryKey: ['download-verify-runs'], queryFn: downloadVerificationApi.list,
    refetchInterval: 5000,
  });
  const details = useQuery({
    queryKey: ['download-verify-items', selected, page],
    queryFn: () => downloadVerificationApi.items(selected!, page),
    enabled: selected !== null,
    refetchInterval: selected === null ? false : 5000,
  });
  const start = useMutation({
    mutationFn: () => downloadVerificationApi.start(remoteRoot, localRoot),
    onSuccess: (run) => {
      setError('');
      setSelected(run.id);
      setPage(1);
      void runs.refetch();
    },
    onError: (err: unknown) => setError(getStructuredApiError(err).message || '启动校验失败'),
  });

  return (
    <div className="nfc-operations-page nfc-page-layout-workbench nfc-download-verify-page">
      <PageHeader title="下载完整性校验"
        description="从 OpenList WebDAV 读取 PikPak 全部文件字节，与 NAS 原始目录逐项 SHA256 比较。只读，不创建副本或修改文件。" />
      <DataPanel title="发起严格校验" description="需要在 API 和 Worker 配置相同的只读 WebDAV 连接；远端必须提供原始字节的同源完整 GET。">
        <p>连接：{config.data?.configured ? config.data.endpoint : '尚未配置 WebDAV（请由管理员配置并重新部署）'}</p>
        <div className="nfc-form-grid">
          <label className="nfc-download-verify-field"><span>WebDAV 远程相对目录（以已配置 /dav/ 为根）</span>
            <input type="text" aria-label="WebDAV 远程相对目录" value={remoteRoot}
              onChange={e => setRemoteRoot(e.target.value)} placeholder="PikPak/电影/2026" />
          </label>
          <div className="nfc-download-verify-field">
            <span>NAS 下载后目录</span>
            <DirectoryPicker value={localRoot} onChange={value => setLocalRoot(typeof value === 'string' ? value : value[0] || '')} />
          </div>
        </div>
        <p role="note">严格模式会重新读取云端全部文件和 NAS 全部文件；例如 1 TB 的文件将产生约 1 TB 远端读取流量。文件路径及大小相同不能替代 SHA256。一旦远端未返回原始字节或扫描变化，结果不会显示为一致。</p>
        {error && <p role="alert">{error}</p>}
        <ConsoleButton variant="primary" loading={start.isPending}
          disabled={!config.data?.configured || !localRoot || start.isPending}
          onClick={() => start.mutate()}>开始只读 SHA256 校验</ConsoleButton>
      </DataPanel>
      <DataPanel title="校验历史" description="任务 completed 仅代表执行结束；只有 VERIFIED_IDENTICAL 才表示双端字节与目录清单通过本次校验。">
        {runs.isError && <p role="alert">读取校验历史失败</p>}
        <div className="nfc-download-verify-table-scroll">
          <table className="nfc-download-verify-table" aria-label="校验历史">
            <thead><tr><th>任务</th><th>远端 / NAS</th><th>状态</th><th>结果</th><th>进度</th><th>操作</th></tr></thead>
            <tbody>
              {(runs.data?.items || []).map(run => <tr key={run.id}>
                <td>#{run.id}</td>
                <td><div>{run.remote_root || '/'}</div><small>{run.local_root}</small></td>
                <td>{run.job_status}</td>
                <td>{verdict[run.result] || run.result}{run.error_code && ' · ' + run.error_code}</td>
                <td>{run.checked}/{run.total}</td>
                <td><ConsoleButton size="sm" onClick={() => { setSelected(run.id); setPage(1); }}>查看条目</ConsoleButton>
                  {' '}<a href={'/tasks?task=' + run.work_job_id}>任务中心</a></td>
              </tr>)}
            </tbody>
          </table>
        </div>
      </DataPanel>
      {selected !== null && <DataPanel title={'校验明细 #' + selected} description="逐路径展示文件 / 目录差异及完整 SHA256 结果，包含空目录。">
        {details.isError && <p role="alert">读取明细失败</p>}
        <div className="nfc-download-verify-table-scroll">
          <table className="nfc-download-verify-table" aria-label="校验明细">
            <thead><tr><th>相对路径</th><th>状态</th><th>远端大小</th><th>NAS 大小</th><th>SHA256</th></tr></thead>
            <tbody>
              {(details.data?.items || []).map(item => <tr key={item.relative_path}>
                <td style={{ overflowWrap: 'anywhere' }}>{item.relative_path}</td>
                <td>{verdict[item.status] || item.status}</td>
                <td>{item.remote_size ?? '—'}</td><td>{item.local_size ?? '—'}</td>
                <td>{item.remote_sha256 && item.local_sha256 ? item.remote_sha256 === item.local_sha256 ? '一致' : '不一致' : '未验证'}</td>
              </tr>)}
            </tbody>
          </table>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <ConsoleButton size="sm" disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>上一页</ConsoleButton>
          <span>第 {page} 页 · 共 {details.data?.total || 0} 项</span>
          <ConsoleButton size="sm" disabled={!details.data || page * 50 >= details.data.total} onClick={() => setPage(p => p + 1)}>下一页</ConsoleButton>
        </div>
      </DataPanel>}
    </div>
  );
};
