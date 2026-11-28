import { useCallback, useLayoutEffect, useRef, type RefObject } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

interface ReadingPosition { list: number; pane: number; document: number }

const positions = new Map<string, ReadingPosition>();

/** Keep positions in this tab only and separate accounts, layouts, and exact folder URLs. */
function rememberPosition(key: string, position: ReadingPosition) {
  positions.delete(key);
  positions.set(key, position);
  if (positions.size <= 100) return;
  const oldest = positions.keys().next().value;
  if (oldest !== undefined) positions.delete(oldest);
}

/** Restore the inner desktop list or the outer phone/tablet reading position after the files arrive. */
export function useFileWorkspacePosition(list: RefObject<HTMLDivElement>, ready: boolean,
  desktop: boolean, userId: string | number | null) {
  const { pathname, search, state, key } = useLocation();
  const navigationType = useNavigationType();
  const href = pathname + search;
  const resume = state?.restoreFileWorkspace === true;
  const positionKey = JSON.stringify([userId, desktop, href]);
  const listParams = new URLSearchParams(search);
  listParams.delete('selected');
  const listKey = JSON.stringify([userId, desktop, pathname, listParams.toString()]);
  const previousList = useRef<string>();
  const savePosition = useCallback(() => {
    const element = list.current;
    if (!ready || !element) return;
    rememberPosition(positionKey, { list: element.scrollTop,
      pane: desktop ? 0 : element.closest('main')?.scrollTop ?? 0,
      document: desktop ? 0 : window.scrollY });
  }, [desktop, list, positionKey, ready]);

  useLayoutEffect(() => {
    const element = list.current;
    if (!ready || !element) return;
    const saved = (resume || navigationType === 'POP') ? positions.get(positionKey) : undefined;
    const listChanged = previousList.current !== undefined && previousList.current !== listKey;
    previousList.current = listKey;
    if (desktop) {
      if (saved || listChanged) element.scrollTop = saved?.list ?? 0;
      savePosition();
      return;
    }

    const pane = element.closest('main');
    // The shell handles outer scrolling on a route change. Apply the specific
    // folder position afterward, including when a return link pushes history.
    let frame: number | undefined;
    if (saved) {
      frame = window.requestAnimationFrame(() => {
        if (pane) pane.scrollTop = saved.pane;
        window.scrollTo({ top: saved.document, behavior: 'instant' });
        savePosition();
      });
    } else savePosition();
    pane?.addEventListener('scroll', savePosition, { passive: true });
    window.addEventListener('scroll', savePosition, { passive: true });
    return () => {
      if (frame !== undefined) window.cancelAnimationFrame(frame);
      pane?.removeEventListener('scroll', savePosition);
      window.removeEventListener('scroll', savePosition);
    };
  }, [desktop, key, list, listKey, navigationType, positionKey, ready, resume, savePosition]);

  return { fileWorkspaceReturn: href, resumed: ready && resume && positions.has(positionKey), savePosition };
}
