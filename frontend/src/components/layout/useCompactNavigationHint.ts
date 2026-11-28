import { useCallback, useEffect, useRef, useState } from 'react';

interface NavigationHint {
  label: string;
  x: number;
  y: number;
}

/** Position a single label outside the rail's clipping and reuse it as the pointer moves. */
export function useCompactNavigationHint(compact: boolean, destination: string) {
  const [hint, setHint] = useState<NavigationHint | null>(null);
  const pending = useRef<number>();
  const recentlyShown = useRef(Number.NEGATIVE_INFINITY);

  const dismiss = useCallback(() => {
    window.clearTimeout(pending.current);
    setHint(null);
  }, []);

  useEffect(() => {
    dismiss();
    if (!compact) return;
    window.addEventListener('resize', dismiss);
    return () => {
      window.removeEventListener('resize', dismiss);
      window.clearTimeout(pending.current);
    };
  }, [compact, destination, dismiss]);

  /** Pause on the first pointer entry. Adjacent items and keyboard focus respond immediately. */
  function show(anchor: HTMLElement, label: string, keyboard = false) {
    if (!compact) return;
    window.clearTimeout(pending.current);
    const apply = () => {
      if (!anchor.isConnected) return;
      const { right, top, height } = anchor.getBoundingClientRect();
      recentlyShown.current = performance.now();
      setHint({
        label, x: right + 11,
        y: Math.max(22, Math.min(window.innerHeight - 22, top + height / 2)),
      });
    };
    if (keyboard || performance.now() - recentlyShown.current < 550) apply();
    else pending.current = window.setTimeout(apply, 190);
  }

  return { hint: compact ? hint : null, show, dismiss };
}
