import { useCallback, useEffect, useRef, useState, type ComponentType } from 'react';

import { useWorkspaceMotionEnabled } from '../../hooks/useWorkspaceMotion';
import type { StorageSceneProps } from './StorageScene';

/** Show the static drive until a visible, motion-enabled location can render WebGL. */
export function StoragePreview({ label }: { label: string }) {
  const host = useRef<HTMLDivElement>(null);
  const enabled = useWorkspaceMotionEnabled();
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
    <div ref={host} className="nfc-storage-preview" role="img" aria-label={label + '存储预览'}
      data-webgl={enabled && ready}>
      <span className="nfc-storage-preview-fallback" aria-hidden="true" />
      {enabled && Scene && <Scene onReady={onReady} />}
    </div>
  );
}
