import dayjs from 'dayjs';

export function formatBytes(bytes: number | null | undefined): string {
  const size = Number(bytes) || 0;
  if (size === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let val = size;
  for (let i = 0; i < units.length; i++) {
    if (Math.abs(val) < 1024 || i === units.length - 1) {
      if (units[i] === 'B') return `${Math.round(val)} B`;
      return `${val.toFixed(2)} ${units[i]}`;
    }
    val /= 1024;
  }
  return `${size} B`;
}

export function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  let s = String(dateStr).trim();
  // Ensure UTC parsing when timezone is absent so browser converts to local timezone (e.g. UTC+8)
  if (!s.endsWith('Z') && !s.includes('+') && !s.includes('GMT')) {
    s = s.replace(' ', 'T') + 'Z';
  }
  const d = dayjs(s);
  if (!d.isValid()) return String(dateStr);
  return d.format('YYYY-MM-DD HH:mm:ss');
}

export function splitLines(text: string): string[] {
  return (text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) {
    return `${s}s`;
  }
  const m = Math.floor(s / 60);
  const remSec = s % 60;
  if (m < 60) {
    return `${m}m ${remSec}s`;
  }
  const h = Math.floor(m / 60);
  const remMin = m % 60;
  return `${h}h ${remMin}m ${remSec}s`;
}

function parseUtcDate(dateStr: string): dayjs.Dayjs {
  let s = String(dateStr).trim();
  if (!s.endsWith('Z') && !s.includes('+') && !s.includes('GMT')) {
    s = s.replace(' ', 'T') + 'Z';
  }
  return dayjs(s);
}

export function formatElapsed(
  startedAt: string | null | undefined,
  finishedAt: string | null | undefined,
  now?: dayjs.Dayjs
): string {
  if (!startedAt) return '-';
  const start = parseUtcDate(startedAt);
  if (!start.isValid()) return '-';

  if (finishedAt) {
    const end = parseUtcDate(finishedAt);
    if (!end.isValid()) return '-';
    const diff = Math.max(0, end.diff(start, 'second'));
    return formatDuration(diff);
  }

  const current = now || dayjs();
  const diff = Math.max(0, current.diff(start, 'second'));
  return formatDuration(diff);
}

export function formatHeartbeatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '-';
  const s = Math.max(0, Math.floor(seconds));
  if (s < 1) return '刚刚';
  if (s < 60) return `${s} 秒前`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  return `${h} 小时前`;
}
