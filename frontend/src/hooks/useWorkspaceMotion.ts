import { useEffect, useSyncExternalStore, type RefObject } from 'react';
import { animate } from 'motion/mini';

const preference = '(prefers-reduced-motion: reduce)';

/** Subscribe to policy changes so a running animation can yield to the OS setting. */
function subscribe(onChange: () => void) {
  if (typeof window === 'undefined') return () => undefined;
  const media = window.matchMedia?.(preference);
  media?.addEventListener?.('change', onChange);
  return () => media?.removeEventListener?.('change', onChange);
}

/** Respect OS policy, including while the workspace is open. */
export function useWorkspaceMotionEnabled(): boolean {
  return useSyncExternalStore(subscribe, () =>
    typeof window !== 'undefined' && !window.matchMedia?.(preference).matches, () => false);
}

/** Animate route entry while preserving the pane DOM, focus, scroll, and query changes. */
export function useWorkspaceMotion(main: RefObject<HTMLElement>, pathname: string, active: boolean) {
  const enabled = useWorkspaceMotionEnabled();
  useEffect(() => {
    const surface = main.current?.firstElementChild;
    if (!active || !enabled || !(surface instanceof HTMLElement) || !surface.animate) return;

    const transition = animate(surface, { opacity: [0.84, 1] }, { duration: 0.17, ease: 'easeOut' });
    return () => transition.cancel();
  }, [active, enabled, main, pathname]);
}
