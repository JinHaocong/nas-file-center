import React from 'react';
import { ConsoleIcon } from './ConsoleIcon';
import { copyExactText, copyUsingSelection, readClipboardWriter } from '../../utils/clipboard';

interface CodePathProps {
  value?: string | null;
  /** An optional reading label. The title and clipboard always use the full value. */
  displayValue?: string;
  muted?: boolean;
  copy?: boolean;
}

/** Read-only filesystem path display: show and copy the exact server-provided string. */
export const CodePath: React.FC<CodePathProps> = ({ value, displayValue, muted = false, copy = true }) => {
  const textRef = React.useRef<HTMLElement>(null);
  const disclosureRef = React.useRef<HTMLButtonElement>(null);
  const copyButtonRef = React.useRef<HTMLButtonElement>(null);
  const textId = React.useId();
  const copyAttempt = React.useRef(0);
  const [clipped, setClipped] = React.useState(false);
  const [expandedValue, setExpandedValue] = React.useState<string | null>(null);
  const expanded = Boolean(value && expandedValue === value);
  const [result, setResult] = React.useState<{
    value: string;
    state: 'copied' | 'failed' | 'unsupported';
  } | null>(null);

  // Only expose disclosure when the current layout actually clips the path.
  // Keep its trigger available while the reader has expanded the text.
  React.useEffect(() => {
    const element = textRef.current;
    if (!element || expanded) return;
    let active = true;
    const measure = () => {
      if (!active) return;
      const truncated = element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1;
      if (!truncated && disclosureRef.current && document.activeElement === disclosureRef.current) {
        copyButtonRef.current?.focus({ preventScroll: true });
      }
      setClipped(truncated);
    };
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    observer?.observe(element);
    if (!observer && typeof window !== 'undefined') window.addEventListener('resize', measure);
    if (typeof document !== 'undefined') void document.fonts?.ready.then(measure);
    return () => {
      active = false;
      observer?.disconnect();
      if (!observer && typeof window !== 'undefined') window.removeEventListener('resize', measure);
    };
  }, [value, displayValue, expanded]);

  React.useEffect(() => {
    setExpandedValue(null);
    setResult(null);
    return () => { copyAttempt.current++; };
  }, [value]);
  React.useEffect(() => {
    if (result?.state !== 'copied') return;
    const timer = setTimeout(() => setResult(null), 2200);
    return () => clearTimeout(timer);
  }, [result]);

  if (!value) {
    return <span className="nfc-code-path nfc-code-path-empty">—</span>;
  }

  /** Ignore a stale clipboard result when the row changes or another copy was requested. */
  const copyPath = async () => {
    const attempt = ++copyAttempt.current;
    const copied = await copyExactText(value, {
      writer: readClipboardWriter(() => navigator.clipboard),
      fallback: copyUsingSelection,
    });
    if (attempt === copyAttempt.current) setResult({ value, state: copied });
  };
  const status = result?.value === value
    ? result.state === 'copied' ? '已复制'
      : result.state === 'failed' ? '复制失败，请手动选择路径' : '不支持自动复制，请手动选择路径'
    : '';

  return (
    <span className={'nfc-code-path nfc-v2-code-path' + (muted ? ' nfc-code-path-muted' : '') +
      (expanded ? ' is-expanded' : '')}>
      <span className="nfc-path-reading-row">
        <code className="nfc-v2-code-path-value" id={textId} ref={textRef} title={value}>
          {expanded ? value : displayValue ?? value}
        </code>
        {(clipped || expanded) && <button type="button" ref={disclosureRef} className="nfc-path-disclosure"
          aria-label={expanded ? '收起完整路径' : '展开完整路径'} aria-expanded={expanded} aria-controls={textId}
          onClick={() => setExpandedValue(expanded ? null : value)}>
          {expanded ? '收起' : '展开'}
        </button>}
        {copy && <button type="button" className="nfc-v2-code-path-copy" ref={copyButtonRef}
          data-copied={status === '已复制' || undefined} title={status || '复制完整路径'} aria-label="复制完整路径"
          onClick={() => { void copyPath(); }}>
          {status === '已复制' ? <ConsoleIcon name="check" size={15} /> : <ConsoleIcon name="copy" size={15} />}
          {status === '已复制' && <small aria-hidden="true">已复制</small>}
        </button>}
      </span>
      <span className="nfc-v2-code-path-feedback" data-error={Boolean(status && status !== '已复制') || undefined}
        aria-live="polite" role="status">
        {status}
      </span>
    </span>
  );
};
