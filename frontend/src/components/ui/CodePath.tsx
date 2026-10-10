import React from 'react';
import { ConsoleIcon } from './ConsoleIcon';
import { copyExactText } from '../../utils/clipboard';

interface CodePathProps {
  value?: string | null;
  muted?: boolean;
}

/** Legacy fallback keeps path copying usable on NAS hosts without secure Clipboard API access. */
function copyUsingSelection(value: string): boolean {
  const field = document.createElement('textarea');
  const activeElement = document.activeElement;
  field.value = value;
  field.readOnly = true;
  field.setAttribute('aria-hidden', 'true');
  field.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
  document.body.appendChild(field);
  try {
    field.focus();
    field.select();
    return document.execCommand('copy');
  } finally {
    field.remove();
    if (activeElement instanceof HTMLElement) activeElement.focus();
  }
}

/** Read-only filesystem path display: show and copy the exact server-provided string. */
export const CodePath: React.FC<CodePathProps> = ({ value, muted = false }) => {
  const [result, setResult] = React.useState<{
    value: string;
    state: 'copied' | 'failed' | 'unsupported';
  } | null>(null);

  if (!value) {
    return <span className="nfc-code-path nfc-code-path-empty">—</span>;
  }

  const copyPath = async () => {
    const copied = await copyExactText(value, {
      writer: navigator.clipboard,
      fallback: copyUsingSelection,
    });
    setResult({ value, state: copied });
  };
  const status = result?.value === value
    ? result.state === 'copied' ? '已复制'
      : result.state === 'failed' ? '复制失败，请手动选择路径' : '不支持自动复制，请手动选择路径'
    : '';

  return (
    <span className={'nfc-code-path nfc-v2-code-path' + (muted ? ' nfc-code-path-muted' : '')}>
      <code className="nfc-v2-code-path-value" title={value}>{value}</code>
      <button type="button" className="nfc-v2-code-path-copy"
        title="复制完整路径" aria-label="复制完整路径"
        onClick={() => { void copyPath(); }}>
        <ConsoleIcon name="copy" size={15} />
      </button>
      <span className="nfc-v2-code-path-feedback" aria-live="polite" role="status">
        {status}
      </span>
    </span>
  );
};
