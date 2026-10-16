/** Preserve the exact display path; the UI must never normalize or interpret it. */
export type ClipboardCopyResult = 'copied' | 'unsupported' | 'failed';
export interface ClipboardWriteOptions {
  writer?: { writeText: (value: string) => Promise<void> } | null;
  fallback?: ((value: string) => boolean) | null;
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
