import type { CloudCopySubmission, CloudFileProvider, CloudTransfer, CloudTransferFile, CloudTransferStatus } from '../../api/cloudFiles';
import type { StructuredApiError } from '../../api/errors';

import { formatBytes } from '../../utils/format';

export const providerLabel: Record<CloudFileProvider, string> = { openlist: 'OpenList', rclone: 'rclone' };

export const statusLabel: Record<CloudTransferStatus, string> = {
  submitting: '正在提交', queued: '排队中', running: '复制中', cancel_requested: '取消中',
  cancelled: '已取消', completed: '已完成', failed: '复制失败', unknown: '状态待确认',
};

/** Only errors known to occur before the first native write can be retried immediately. */
export function cloudSubmissionRejected({ code, status }: StructuredApiError): boolean {
  return code === 'CLOUD_COPY_NOT_SUBMITTED' || status === 403 || status === 409 || status === 422;
}

/** Use server-provided counts without treating unacknowledged objects as submitted. */
export function formatCloudSubmission(receipt: CloudCopySubmission): string {
  const skipped = receipt.skipped_names?.length ?? 0;
  const skipText = skipped ? '已跳过 ' + skipped + ' 个已有文件' : '';
  if (!('id' in receipt)) return skipText || '没有新的复制任务';
  const confirmed = receipt.submitted_count;
  const count = typeof confirmed === 'number' && Number.isSafeInteger(confirmed) && confirmed >= 0 ? confirmed : null;
  const title = receipt.error
    ? [count === null ? '' : '已确认提交 ' + count + ' 项', '部分提交结果待确认'].filter(Boolean).join('，')
    : count === null ? '复制任务已提交' : '已提交 ' + count + ' 项';
  return [title, skipText].filter(Boolean).join('，');
}

/** Read a compact display type from the real file name and retain generic labels for unknown types. */
export function describeCloudFile(name: string, directory = false) {
  const extension = /\.([A-Za-z0-9]{1,8})$/.exec(name.slice(1))?.[1].toUpperCase();
  const label = directory ? '文件夹' : extension || '文件';
  const icon = directory ? 'folder'
    : /^(MP4|MOV|MKV|AVI|WEBM|MPEG)$/.test(label) ? 'play'
      : /^(MP3|WAV|FLAC|M4A|AAC|OGG)$/.test(label) ? 'activity'
        : /^(PNG|JPE?G|WEBP|GIF|SVG|AVIF|HEIC)$/.test(label) ? 'image'
          : /^(ZIP|RAR|7Z|TAR|GZ|BZ2|XZ)$/.test(label) ? 'archive' : 'file-text';
  return { label, icon } as const;
}

/** Keep polling only while the provider may report a newer outcome. */
export function isLiveTransfer(status: CloudTransferStatus | undefined): boolean {
  return status === 'submitting' || status === 'queued' || status === 'running' || status === 'cancel_requested';
}

/** Read an optional byte counter without turning missing telemetry into zero. */
export function displayBytes(bytes: number | null | undefined): string {
  return typeof bytes === 'number' && Number.isFinite(bytes) && bytes >= 0 ? formatBytes(bytes) : '—';
}

/** Mark derived throughput separately from an authoritative native speed. */
export function displaySpeed(bytesPerSecond: number | null | undefined, estimated = false): string {
  const formatted = displayBytes(bytesPerSecond);
  return formatted === '—' ? formatted : formatted + '/s' + (estimated ? '（估算）' : '');
}

/** Estimate throughput only across consecutive observations of the same running file. */
export function estimateOpenListSpeed(previous: CloudTransfer, current: CloudTransfer, elapsedMs: number): CloudTransfer {
  if (current.provider !== 'openlist' || previous.id !== current.id || elapsedMs < 500 || elapsedMs > 15_000) return current;
  const previousFiles = new Map<string, CloudTransferFile | null>();
  for (const file of previous.files) {
    previousFiles.set(file.name, previousFiles.has(file.name) ? null : file);
  }
  const files = current.files.map(file => {
    const older = previousFiles.get(file.name);
    if (!older || file.status !== 'running' || older.status !== 'running' || file.speed !== null ||
        file.bytes === null || older.bytes === null || file.total_bytes === null ||
        file.total_bytes !== older.total_bytes || file.total_bytes <= 0 ||
        file.bytes > file.total_bytes || older.bytes < 0 || file.bytes < older.bytes) return file;
    const speed = (file.bytes - older.bytes) * 1000 / elapsedMs;
    return Number.isFinite(speed) ? { ...file, speed, speed_estimated: true } : file;
  });
  const runningFiles = files.filter(file => file.status === 'running');
  const canEstimateTotal = current.speed === null && runningFiles.length > 0 && runningFiles.every(file => file.speed !== null);
  return {
    ...current,
    files,
    speed: canEstimateTotal ? runningFiles.reduce((sum, file) => sum + (file.speed ?? 0), 0) : current.speed,
    speed_estimated: canEstimateTotal || current.speed_estimated,
  };
}

/** Construct the installed provider's transfer page beneath its configured base URL. */
export function nativeTransferPage(provider: CloudFileProvider, address?: string | null): string | undefined {
  if (!address) return undefined;
  try {
    const url = new URL(address);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return undefined;
    const terminal = provider === 'openlist' ? '/@manage/tasks/copy' : '/transfers';
    url.pathname = url.pathname.replace(/\/+$/, '') + terminal;
    url.search = '';
    url.hash = '';
    return url.href;
  } catch {
    return undefined;
  }
}

/** Open a finished OpenList folder's verification with exact provider and destination paths. */
export function verificationPage(verification: CloudTransfer['verification']): string {
  if (!verification) return '/download-verification';
  return '/download-verification?' + new URLSearchParams({
    source: verification.source_id,
    remote: verification.remote_root,
    directory: verification.local_root,
  });
}
