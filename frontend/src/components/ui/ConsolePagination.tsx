import React from 'react';
import { ConsoleIcon } from './ConsoleIcon';
import { getPaginationState, parseJumpPage } from './paginationModel';

interface Props {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number, pageSize: number) => void;
  pageSizes?: readonly number[];
}

/** Navigate a controlled paginated result with buttons, a direct page entry or a page-size change. */
export const ConsolePagination: React.FC<Props> = ({
  page, pageSize, total, onChange, pageSizes = [10, 20, 50, 100],
}) => {
  const size = Number.isInteger(pageSize) && pageSize > 0 ? pageSize : 20;
  const count = Number.isFinite(total) ? Math.max(0, Math.floor(total)) : 0;
  const { pages, current, start, end } = getPaginationState(page, size, count);
  const [draft, setDraft] = React.useState<string | null>(null);
  const [invalid, setInvalid] = React.useState(false);
  const attemptedCorrection = React.useRef('');
  const input = React.useRef<HTMLInputElement>(null);
  const errorId = React.useId();
  const sizeOptions = pageSizes.includes(size) ? pageSizes : [size, ...pageSizes];
  const typed = draft ?? String(current);

  React.useEffect(() => {
    setDraft(null);
    setInvalid(false);
  }, [current, pages, size]);

  React.useEffect(() => {
    // During a server fetch some callers temporarily report zero rows. Wait
    // for a positive total before redirecting a page removed from the dataset.
    if (!count || page === current) {
      attemptedCorrection.current = '';
      return;
    }
    const correction = `${page}/${pages}/${size}`;
    if (attemptedCorrection.current !== correction) {
      attemptedCorrection.current = correction;
      onChange(current, size);
    }
  }, [count, page, pages, current, size, onChange]);

  /** Validate against the live page count before requesting a new page. */
  function jump() {
    const next = parseJumpPage(typed, pages);
    if (next === null) {
      setInvalid(true);
      input.current?.focus();
      return;
    }
    setInvalid(false);
    setDraft(null);
    if (next !== current) onChange(next, size);
  }

  return (
    <nav className="nfc-console-pagination" aria-label="列表分页">
      <span className="nfc-console-page-summary">显示 {start}–{end} / 共 {count} 条</span>
      <div className="nfc-console-page-buttons">
        <button type="button" disabled={current <= 1}
          aria-label="上一页" onClick={() => onChange(current - 1, size)}>
          <ConsoleIcon name="chevron-right" className="nfc-console-page-prev" size={17} />
        </button>
        {pages > 1 ? <div className="nfc-page-jump">
          <input ref={input} type="text" inputMode="numeric" autoComplete="off" aria-label="跳转页码"
            size={Math.min(8, String(pages).length)}
            aria-invalid={invalid || undefined} aria-describedby={invalid ? errorId : undefined} value={typed}
            onChange={event => { setDraft(event.target.value); setInvalid(false); }}
            onKeyDown={event => {
              // Some paginators live inside a draft form. Enter must remain a page navigation.
              if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                event.preventDefault();
                event.stopPropagation();
                jump();
              }
            }} />
          <span aria-label={`共 ${pages} 页`}>/ {pages} 页</span>
          <button type="button" className="nfc-page-jump-apply" aria-label="转到输入页码"
            disabled={typed.trim() === String(current)} onClick={jump}>转到</button>
        </div> : <span aria-hidden="true">第 1 / 1 页</span>}
        <span className="nfc-pagination-live" aria-live="polite">第 {current} / {pages} 页</span>
        <button type="button" disabled={current >= pages}
          aria-label="下一页" onClick={() => onChange(current + 1, size)}>
          <ConsoleIcon name="chevron-right" size={17} />
        </button>
      </div>
      <label className="nfc-console-page-size">
        每页
        <select value={size} aria-label="每页记录数" onChange={event => {
          setDraft(null);
          setInvalid(false);
          onChange(1, Number(event.target.value));
        }}>
          {sizeOptions.map(option => <option key={option} value={option}>{option} 条</option>)}
        </select>
      </label>
      {invalid && <span id={errorId} className="nfc-pagination-error" role="alert">请输入 1 到 {pages} 之间的整数页码。</span>}
    </nav>
  );
};
