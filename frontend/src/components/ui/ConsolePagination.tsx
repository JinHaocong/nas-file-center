import React from 'react';
import { ConsoleIcon } from './ConsoleIcon';

interface Props {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number, pageSize: number) => void;
  pageSizes?: readonly number[];
}

export const ConsolePagination: React.FC<Props> = ({
  page, pageSize, total, onChange, pageSizes = [10, 20, 50, 100],
}) => {
  const pages = Math.max(1, Math.ceil(Math.max(0, total) / pageSize));
  const current = Math.max(1, Math.min(page, pages));
  const start = total > 0 ? (current - 1) * pageSize + 1 : 0;
  const end = Math.min(total, current * pageSize);
  return (
    <nav className="nfc-console-pagination" aria-label="列表分页">
      <span className="nfc-console-page-summary">显示 {start}–{end} / 共 {total} 条</span>
      <div className="nfc-console-page-buttons">
        <button type="button" disabled={current <= 1}
          aria-label="上一页" onClick={() => onChange(current - 1, pageSize)}>
          <ConsoleIcon name="chevron-right" className="nfc-console-page-prev" size={17} />
        </button>
        <span aria-live="polite">第 {current} / {pages} 页</span>
        <button type="button" disabled={current >= pages}
          aria-label="下一页" onClick={() => onChange(current + 1, pageSize)}>
          <ConsoleIcon name="chevron-right" size={17} />
        </button>
      </div>
      <label className="nfc-console-page-size">
        每页
        <select value={pageSize} aria-label="每页记录数"
          onChange={event => onChange(1, Number(event.target.value))}>
          {pageSizes.map(size => <option key={size} value={size}>{size} 条</option>)}
        </select>
      </label>
    </nav>
  );
};
