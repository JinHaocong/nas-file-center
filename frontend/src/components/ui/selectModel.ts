/**
 * Fail closed for a native filter selection that is stale, disabled, absent,
 * or ambiguous in the current option snapshot. This never supplies a fallback
 * option or changes caller-owned filter state.
 */
export function isSelectableConsoleOption(
  value: string,
  options: readonly { value: string; disabled?: boolean }[],
): boolean {
  const matches = options.filter(option => option.value === value);
  return matches.length === 1 && matches[0].disabled !== true;
}
