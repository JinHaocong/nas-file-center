/** Preserve the exact display path; the UI must never normalize or interpret it. */
export type ClipboardCopyResult = 'copied' | 'unsupported' | 'failed';
export interface ClipboardWriteOptions {
  writer?: { writeText: (value: string) => Promise<void> } | null;
  fallback?: ((value: string) => boolean) | null;
}

export async function copyExactText(
  value: string,
  { writer, fallback }: ClipboardWriteOptions,
): Promise<ClipboardCopyResult> {
  if (writer?.writeText) {
    try {
      await writer.writeText(value);
      return 'copied';
    } catch {
      // Clipboard API can be blocked on non-HTTPS NAS origins; try selection fallback.
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
