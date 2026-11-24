export interface PaginationState {
  pages: number;
  current: number;
  start: number;
  end: number;
}

/** Clamp a requested page to the current dataset and derive its displayed range. */
export function getPaginationState(page: number, pageSize: number, total: number): PaginationState {
  const size = Number.isInteger(pageSize) && pageSize > 0 ? pageSize : 20;
  const count = Number.isFinite(total) ? Math.max(0, Math.floor(total)) : 0;
  const pages = Math.max(1, Math.ceil(count / size));
  const requested = Number.isFinite(page) ? Math.floor(page) : 1;
  const current = Math.max(1, Math.min(requested, pages));
  const start = count === 0 ? 0 : (current - 1) * size + 1;
  const end = Math.min(count, current * size);
  return { pages, current, start, end };
}

/** Accept whole decimal page numbers in the current range. */
export function parseJumpPage(text: string, pages: number): number | null {
  const input = text.trim();
  if (!/^\d+$/.test(input)) return null;
  const page = Number(input);
  return Number.isSafeInteger(page) && page >= 1 && page <= pages ? page : null;
}
