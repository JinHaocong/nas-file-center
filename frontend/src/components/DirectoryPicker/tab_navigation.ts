/** Horizontal WAI-ARIA tablist navigation for the shared directory browser.
 * Only horizontal arrows navigate; Tab exits the tablist to the active panel.
 * This function has no filesystem or React dependencies.
 */
export type DirectoryTab = 'browser' | 'favorites' | 'recent';

export const DIRECTORY_TABS: readonly DirectoryTab[] = ['browser', 'favorites', 'recent'];

export function nextDirectoryTab(current: DirectoryTab, key: string): DirectoryTab | null {
  const position = DIRECTORY_TABS.indexOf(current);
  if (position < 0) return null;
  if (key === 'Home') return DIRECTORY_TABS[0];
  if (key === 'End') return DIRECTORY_TABS[DIRECTORY_TABS.length - 1];
  if (key === 'ArrowRight') return DIRECTORY_TABS[(position + 1) % DIRECTORY_TABS.length];
  if (key === 'ArrowLeft') return DIRECTORY_TABS[(position - 1 + DIRECTORY_TABS.length) % DIRECTORY_TABS.length];
  return null;
}
