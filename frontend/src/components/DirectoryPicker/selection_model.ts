/**
 * UI path checking is only a supplementary guard. Every directory operation and
 * final scan submission remains subject to the backend ALLOWED_ROOTS/PathGuard.
 */
export function isWithinDirectoryRoots(path: string, allowedRoots: readonly string[]): boolean {
  if (!path.startsWith('/') || path.split('/').some(segment => segment === '.' || segment === '..')) return false;
  const clean = (value: string) => value.replace(/\/+$/, '') || '/';
  const current = clean(path);
  return allowedRoots.filter(root => root.startsWith('/')).some(root => {
    const base = clean(root);
    return current === base || (base === '/' ? current.startsWith('/') : current.startsWith(base + '/'));
  });
}

export function initialDirectorySelection(
  selected: string | string[] | undefined, multiple: boolean,
): string[] {
  const values = (Array.isArray(selected) ? selected : selected ? [selected] : [])
    .map(value => value.trim()).filter(Boolean);
  return multiple ? [...new Set(values)] : values.slice(0, 1);
}

export function toggleDirectorySelection(
  current: readonly string[], path: string, multiple: boolean,
): string[] {
  if (!path.trim()) return [...current];
  if (!multiple) return [path];
  return current.includes(path) ? current.filter(value => value !== path) : [...current, path];
}

export function resolveDirectorySelection(
  current: readonly string[], fallbackPath: string, multiple: boolean,
): string | string[] | null {
  const values = current.length ? [...current] : fallbackPath ? [fallbackPath] : [];
  if (!values.length) return null;
  return multiple ? values : values[0];
}
