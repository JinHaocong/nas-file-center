import { useState } from 'react';

import { CodePath } from './CodePath';
import { ConsoleButton } from './ConsoleButton';
import { ConsoleIcon } from './ConsoleIcon';

/** Return the longest shared directory boundary, leaving the final component of each path visible. */
export function commonDirectoryPrefix(paths: readonly string[]): string | undefined {
  if (paths.length < 2 || !paths[0].startsWith('/')) return undefined;
  let prefix = paths[0].slice(0, paths[0].lastIndexOf('/'));
  for (const path of paths) {
    while (prefix && !path.startsWith(prefix + '/')) {
      prefix = prefix.slice(0, prefix.lastIndexOf('/'));
    }
    if (!prefix) return undefined;
  }
  return prefix;
}

/** Shorten only the painted text; the original path remains the copy source. */
export function relativePathLabel(path: string, prefix: string | undefined): string {
  return prefix && path.startsWith(prefix + '/') ? path.slice(prefix.length + 1) : path;
}

/** Keep one expand/collapse choice for the current shared root. */
export function usePathPrefix(prefix: string | undefined) {
  const [expandedPrefix, setExpandedPrefix] = useState<string>();
  const expanded = prefix !== undefined && expandedPrefix === prefix;
  return {
    prefix,
    expanded,
    toggle: () => setExpandedPrefix(expanded ? undefined : prefix),
    displayPath: (path: string) => relativePathLabel(path, expanded ? undefined : prefix),
  };
}

/** Place the shared path once above an aligned comparison or result table. */
export function PathPrefixDisclosure({ prefix, expanded, toggle, compact = false }:
  ReturnType<typeof usePathPrefix> & { compact?: boolean }) {
  if (!prefix) return null;
  const label = expanded ? '折叠公共路径' : '展开公共路径';
  const slash = prefix.lastIndexOf('/');
  const shortened = compact && !expanded && slash > 0 ? '…' + prefix.slice(slash) + '/' : undefined;
  return (
    <div className={'nfc-path-prefix-disclosure' + (compact ? ' is-compact' : '')}>
      <ConsoleIcon name="folder-open" size={15} />
      {!compact && <span>公共路径</span>}
      <CodePath value={prefix} displayValue={shortened} />
      <ConsoleButton aria-label={label} aria-expanded={expanded} size="sm" variant="ghost"
        onClick={toggle}>{label}</ConsoleButton>
    </div>
  );
}
