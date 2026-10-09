export interface PaginationState {
  pages: number;
  current: number;
  start: number;
  end: number;
}

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
