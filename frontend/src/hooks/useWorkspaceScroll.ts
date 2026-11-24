import { useLayoutEffect, useRef, type RefObject } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

interface ScrollPosition { pane: number; window: number }

/** Restore the desktop pane or mobile document when returning to a previously read page. */
export function useWorkspaceScroll(main: RefObject<HTMLElement>, authenticated: boolean) {
  const { key, pathname, hash } = useLocation();
  const navigationType = useNavigationType();
  const positions = useRef(new Map<string, ScrollPosition>());
  const previousPath = useRef<string>();

  useLayoutEffect(() => {
    const pane = main.current;
    if (!pane || !authenticated) {
      previousPath.current = undefined;
      positions.current.clear();
      return;
    }
    const saved = navigationType === 'POP' ? positions.current.get(key) : undefined;
    const changedPage = previousPath.current !== undefined && previousPath.current !== pathname;
    previousPath.current = pathname;
    let observer: ResizeObserver | undefined;
    let timeout: number | undefined;
    let restoring = false;

    function stopRestoring() {
      observer?.disconnect();
      window.clearTimeout(timeout);
      restoring = false;
    }

    function remember() {
      if (!restoring) positions.current.set(key, { pane: pane!.scrollTop, window: window.scrollY });
      if (positions.current.size > 100) {
        const oldest = positions.current.keys().next().value;
        if (oldest !== undefined) positions.current.delete(oldest);
      }
    }

    if (changedPage && !hash) {
      pane.focus({ preventScroll: true });
      const target = saved ?? { pane: 0, window: 0 };
      const restore = () => {
        pane.scrollTop = target.pane;
        window.scrollTo({ top: target.window, behavior: 'instant' });
        if (Math.abs(pane.scrollTop - target.pane) < 2 && Math.abs(window.scrollY - target.window) < 2) stopRestoring();
      };
      restoring = true;
      restore();
      // On Back, the saved position can be below the loading state. Retry as
      // the real content grows, but always yield immediately to user input.
      if (restoring && pane.firstElementChild && typeof ResizeObserver !== 'undefined') {
        observer = new ResizeObserver(restore);
        observer.observe(pane.firstElementChild);
        timeout = window.setTimeout(stopRestoring, 1800);
      } else {
        stopRestoring();
      }
    }
    remember();
    pane.addEventListener('scroll', remember, { passive: true });
    window.addEventListener('scroll', remember, { passive: true });
    for (const event of ['wheel', 'touchstart', 'keydown', 'pointerdown']) window.addEventListener(event, stopRestoring, { passive: true });
    return () => {
      pane.removeEventListener('scroll', remember);
      window.removeEventListener('scroll', remember);
      for (const event of ['wheel', 'touchstart', 'keydown', 'pointerdown']) window.removeEventListener(event, stopRestoring);
      stopRestoring();
    };
  }, [authenticated, hash, key, main, navigationType, pathname]);
}
