import { useEffect, useRef, type KeyboardEvent } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { ChevronLeft, Film } from 'lucide-react';

import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { MediaThumbnail, mediaThumbnailKind } from '../../components/ui/MediaThumbnail';

import { useResponsive } from '../../hooks/useResponsive';
import { useWorkspaceMotionEnabled } from '../../hooks/useWorkspaceMotion';
import { formatBytes } from '../../utils/format';
import { animateQuickLookPanel } from './quickLookMotion';
import { useQuickLookSwipe } from './useQuickLookSwipe';

import type { DirectoryItem } from '../../types';

interface WorkspaceQuickLookProps {
  entries: DirectoryItem[];
  path: string | null;
  onSelect: (entry: DirectoryItem) => void;
  onClose: () => void;
  restoreFocus: () => void;
}

const stripLimit = 7;

/** Preview the result page using the same permission-checked thumbnails as the workspace. */
export function WorkspaceQuickLook({ entries, path, onSelect, onClose, restoreFocus }: WorkspaceQuickLookProps) {
  const panel = useRef<HTMLDivElement>(null);
  const closer = useRef<HTMLButtonElement>(null);
  const panelMotion = useRef<Animation | null>(null);
  const closing = useRef(false);
  const motion = useWorkspaceMotionEnabled();
  const { isMobile } = useResponsive();
  const touchMotion = motion && (isMobile || (typeof window !== 'undefined' && window.matchMedia?.('(any-pointer: coarse)').matches));
  const index = entries.findIndex(entry => entry.path === path);
  const entry = entries[index];
  const previous = index > 0 ? entries[index - 1] : undefined;
  const next = index >= 0 ? entries[index + 1] : undefined;
  const kind = entry ? mediaThumbnailKind(entry.path) : undefined;
  const stripStart = Math.max(0, Math.min(index - Math.floor(stripLimit / 2), entries.length - stripLimit));
  const strip = entries.slice(stripStart, stripStart + stripLimit);
  const swipe = useQuickLookSwipe({
    path, motion: touchMotion, previous: Boolean(previous), next: Boolean(next),
    onStep: direction => choose(direction === -1 ? previous : next),
  });
  const { track, reset, ...swipeHandlers } = swipe;

  useEffect(() => () => panelMotion.current?.cancel(), []);
  useEffect(() => {
    if (motion || !panelMotion.current) return;
    panelMotion.current.cancel();
    panelMotion.current = null;
    if (closing.current) onClose();
  }, [motion, onClose]);

  /** Keep the active file stable while the viewer returns to its selected row. */
  function choose(candidate?: DirectoryItem) {
    if (candidate && !closing.current) onSelect(candidate);
  }

  /** Let keyboard, arrow and thumbnail controls take over from a swipe. */
  function select(candidate?: DirectoryItem) {
    if (!candidate || closing.current) return;
    reset();
    choose(candidate);
  }

  /** Direction keys are local to the overlay and leave normal buttons accessible. */
  function browse(event: KeyboardEvent<HTMLDivElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    select(event.key === 'ArrowLeft' ? previous : next);
  }

  /** Let Radix retain its focus trap through the return transition. */
  function dismiss() {
    if (closing.current) return;
    reset();
    const animation = motion && panel.current && entry &&
      animateQuickLookPanel(panel.current, entry.path, false, panelMotion.current);
    if (!animation) {
      onClose();
      return;
    }
    closing.current = true;
    panelMotion.current = animation;
    void animation.finished.then(() => {
      if (panel.current && panelMotion.current === animation) onClose();
    }, () => {});
  }

  /** Start at the filesystem thumbnail and move focus without shifting its scroll position. */
  function openViewer(event: Event) {
    event.preventDefault();
    closing.current = false;
    closer.current?.focus({ preventScroll: true });
    if (motion && panel.current && entry) {
      panelMotion.current = animateQuickLookPanel(panel.current, entry.path, true, panelMotion.current) ?? null;
    }
  }

  const slides = entry ? (touchMotion ? [previous, entry, next] : [entry]) : [];
  const descriptor = entry && [kind === 'video' ? '视频封面' : '图片', entry.size == null ? '' : formatBytes(entry.size)]
    .filter(Boolean).join(' · ');

  return <Dialog.Root open={Boolean(entry)} onOpenChange={open => { if (!open) dismiss(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-quicklook-overlay" />
      <Dialog.Content ref={panel} className="nfc-quicklook-dialog" onKeyDown={browse}
        onOpenAutoFocus={openViewer}
        onCloseAutoFocus={event => {
          event.preventDefault();
          reset();
          closing.current = false;
          panelMotion.current?.cancel();
          panelMotion.current = null;
          restoreFocus();
        }}>
        <header className="nfc-quicklook-heading">
          <span className="nfc-quicklook-grip" aria-hidden="true" />
          <span className="nfc-quicklook-kind" aria-hidden="true">
            {kind === 'video' ? <Film size={17} /> : <ConsoleIcon name="image" size={17} />}
          </span>
          <div className="nfc-quicklook-heading-copy">
            <Dialog.Title title={entry?.name}>{entry?.name ?? '快速查看'}</Dialog.Title>
            <Dialog.Description>{descriptor}</Dialog.Description>
          </div>
          {entry && <span className="nfc-quicklook-index" aria-live="polite">{index + 1} / {entries.length}</span>}
          <Dialog.Close asChild>
            <button type="button" ref={closer} className="nfc-quicklook-control" aria-label="关闭快览">
              <ConsoleIcon name="x" size={17} />
            </button>
          </Dialog.Close>
        </header>
        {entry && <div className="nfc-quicklook-media" {...swipeHandlers}>
          <div className="nfc-quicklook-track" ref={track}>
            {slides.map(candidate => {
              if (!candidate) return null;
              const active = candidate.path === entry.path;
              return <div className="nfc-quicklook-slide" key={candidate.path} aria-hidden={!active || undefined}
                data-placement={active ? 'current' : candidate.path === previous?.path ? 'previous' : 'next'}>
                <MediaThumbnail path={candidate.path} kind={mediaThumbnailKind(candidate.path) ?? 'file'} size="cover" />
                <p className="nfc-quicklook-unavailable" role="status">此文件没有可用缩略图</p>
                {active && kind === 'video' && <span className="nfc-quicklook-video-mark">
                  <Film size={14} aria-hidden="true" />视频封面
                </span>}
              </div>;
            })}
          </div>
          <button type="button" className="nfc-quicklook-control is-previous" onClick={() => select(previous)}
            aria-label="上一项" disabled={!previous}><ChevronLeft size={17} aria-hidden="true" /></button>
          <button type="button" className="nfc-quicklook-control is-next" onClick={() => select(next)}
            aria-label="下一项" disabled={!next}><ConsoleIcon name="chevron-right" size={17} /></button>
          {(previous || next) && <span className="nfc-quicklook-swipe-caption" aria-hidden="true">↔ 左右滑动</span>}
        </div>}
        {entry && <div className="nfc-quicklook-strip" role="group" aria-label="当前页缩略图">
          {strip.map(candidate => <button type="button" key={candidate.path} title={candidate.name}
            aria-label={candidate.name} aria-pressed={entry.path === candidate.path} onClick={() => select(candidate)}>
            <MediaThumbnail path={candidate.path} kind={mediaThumbnailKind(candidate.path) ?? 'file'} size="small" />
          </button>)}
        </div>}
        <footer className="nfc-quicklook-footer">
          <span className="nfc-quicklook-key-hints"><kbd>←</kbd><kbd>→</kbd> 切换文件 <kbd>Esc</kbd> 返回当前文件</span>
          <span className="nfc-quicklook-touch-hints">关闭后回到当前文件</span>
        </footer>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
