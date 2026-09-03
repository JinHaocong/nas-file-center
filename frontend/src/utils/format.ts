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
  const d = dayjs(dateStr);
  if (!d.isValid()) return String(dateStr);
  return d.format('YYYY-MM-DD HH:mm:ss');
}

export function splitLines(text: string): string[] {
  return (text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}
