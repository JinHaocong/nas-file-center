/**
 * Literal substring replacement helper for Workflow V1 RenameStep.
 * Does NOT evaluate regex, capture groups, or regex special characters.
 */
export function applyLiteralRename(name: string, pattern: string, replacement: string): string {
  if (!pattern) return name;
  return name.split(pattern).join(replacement);
}
