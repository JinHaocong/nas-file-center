/** Preserve the exact display path; the UI must never normalize or interpret it. */
export type ClipboardCopyResult = 'copied' | 'unsupported' | 'failed';
export interface ClipboardWriteOptions {
  writer?: { writeText: (value: string) => Promise<void> } | null;
  fallback?: ((value: string) => boolean) | null;
}

/** Copy through a temporary selection on browsers without the secure clipboard API. */
export function copyUsingSelection(value: string, within: HTMLElement = document.body): boolean {
  const field = document.createElement('textarea');
  const activeElement = document.activeElement;
  field.value = value;
  field.readOnly = true;
  field.setAttribute('aria-hidden', 'true');
  field.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
  within.appendChild(field);
  try {
    field.focus({ preventScroll: true });
    field.select();
    return document.execCommand('copy');
  } finally {
    field.remove();
    if (activeElement instanceof HTMLElement) activeElement.focus({ preventScroll: true });
  }
}

/** Some restricted browsers throw even while resolving navigator.clipboard. */
export function readClipboardWriter(
  read: () => ClipboardWriteOptions['writer'],
): ClipboardWriteOptions['writer'] {
  try {
    return read();
  } catch {
    return null;
  }
}

export async function copyExactText(
  value: string,
  { writer, fallback }: ClipboardWriteOptions,
): Promise<ClipboardCopyResult> {
  if (writer) {
    try {
      // A host may expose clipboard but deny reading writeText itself.
      if (typeof writer.writeText === 'function') {
        await writer.writeText(value);
        return 'copied';
      }
    } catch {
      // Clipboard access or the write can be denied; try selection fallback.
    }
  }

  if (fallback) {
    try {
      return fallback(value) ? 'copied' : 'failed';
    } catch {
      return 'failed';
    }
  }
  return writer ? 'failed' : 'unsupported';
}
