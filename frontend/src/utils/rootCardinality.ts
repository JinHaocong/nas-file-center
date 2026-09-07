export function normalizeSelectedRoots(
  roots: number[] | undefined,
  mode: 'file' | 'organizer'
): number[] | undefined {
  if (!roots || !Array.isArray(roots) || roots.length === 0) {
    return undefined;
  }
  if (mode === 'organizer') {
    return [roots[0]];
  }
  // File mode: max 16 roots
  return roots.slice(0, 16);
}
