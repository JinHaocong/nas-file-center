import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type ComponentType } from 'react';

import { useWorkspaceMotionEnabled } from '../../hooks/useWorkspaceMotion';
import type { StorageSceneProps } from './StorageScene';

const pointerQuery = '(any-hover: hover) and (any-pointer: fine)';

/** Touch-only devices can use the same static render without loading the scene. */
function subscribePointer(change: () => void) {
  const media = typeof window === 'undefined' ? undefined : window.matchMedia?.(pointerQuery);
  media?.addEventListener?.('change', change);
  return () => media?.removeEventListener?.('change', change);
}

/** Read the device's current ability to hover with a fine pointer. */
function hasHoverPointer() {
  return typeof window !== 'undefined' && Boolean(window.matchMedia?.(pointerQuery).matches);
}

/** Show the static drive until a visible, motion-enabled location can render WebGL. */
export function StoragePreview({ label }: { label: string }) {
  const host = useRef<HTMLDivElement>(null);
  const motion = useWorkspaceMotionEnabled();
  const pointer = useSyncExternalStore(subscribePointer, hasHoverPointer, () => false);
  const enabled = motion && pointer;
  const [Scene, setScene] = useState<ComponentType<StorageSceneProps> | null>(null);
  const [ready, setReady] = useState(false);
  const onReady = useCallback((next: boolean) => setReady(next), []);

  useEffect(() => {
    const node = host.current;
    if (!enabled || !node || typeof IntersectionObserver === 'undefined' ||
        typeof WebGL2RenderingContext === 'undefined') return;

    let current = true;
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      observer.disconnect();
      void import('./StorageScene').then(module => {
        if (current) setScene(() => module.StorageScene);
      }).catch(() => { /* The static preview stays visible when the chunk is unavailable. */ });
    });
    observer.observe(node);
    return () => { current = false; observer.disconnect(); };
  }, [enabled]);

  return (
    <div ref={host} className="nfc-storage-preview" role="img" aria-label={`${label} · 极空间 Z4 Pro 珍珠白`}
      data-webgl={enabled && ready}>
      <span className="nfc-storage-preview-fallback" aria-hidden="true" />
      {enabled && Scene && <Scene onReady={onReady} />}
    </div>
  );
}
