/** Presentation-only directory helpers. Backend PathGuard is the authoritative path check. */
export const splitDirectoryPathLines = (text: string): string[] =>
  text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);

export interface DirectoryBreadcrumb {
  baseRoot: string;
  segments: { name: string; path: string }[];
}

const trimTrailingSlash = (path: string): string => path.replace(/\/+$/, '') || '/';

export function buildDirectoryBreadcrumb(
  currentPath: string,
  allowedRoots: readonly string[],
): DirectoryBreadcrumb | null {
  if (!currentPath.startsWith('/') || !allowedRoots.length) return null;
  const current = trimTrailingSlash(currentPath);
  const roots = allowedRoots.filter(root => root.startsWith('/')).map(trimTrailingSlash);
  const matches = roots.filter(root =>
    current === root || (root === '/' ? current.startsWith('/') : current.startsWith(root + '/')),
  ).sort((a, b) => b.length - a.length);
  if (!matches.length) return null;

  const baseRoot = matches[0];
  const relative = current === baseRoot ? '' : current.slice(baseRoot === '/' ? 1 : baseRoot.length + 1);
  const parts = relative.split('/').filter(Boolean);
  // Breadcrumb must not construct navigable links for traversal segments.
  if (parts.some(part => part === '.' || part === '..')) return null;
  return {
    baseRoot,
    segments: parts.map((name, index) => ({
      name,
      path: (baseRoot === '/' ? '' : baseRoot) + '/' + parts.slice(0, index + 1).join('/'),
    })),
  };
}
