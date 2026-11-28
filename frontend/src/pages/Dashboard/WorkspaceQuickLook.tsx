import { useRef, type KeyboardEvent, type PointerEvent } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Film } from 'lucide-react';

import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { MediaThumbnail, mediaThumbnailKind } from '../../components/ui/MediaThumbnail';

import { formatBytes } from '../../utils/format';

import type { DirectoryItem } from '../../types';

interface WorkspaceQuickLookProps {
  entries: DirectoryItem[];
  path: string | null;
  onSelect: (entry: DirectoryItem) => void;
  onClose: () => void;
  restoreFocus: () => void;
}

const stripLimit = 7;
const swipeThreshold = 42;

/** Preview the current result page without reading original images or streaming videos. */
export function WorkspaceQuickLook({ entries, path, onSelect, onClose, restoreFocus }: WorkspaceQuickLookProps) {
  const closer = useRef<HTMLButtonElement>(null);
  const gesture = useRef<{ x: number; y: number; id: number } | null>(null);
  const index = entries.findIndex(entry => entry.path === path);
  const entry = entries[index];
  const kind = entry ? mediaThumbnailKind(entry.path) : undefined;
  const stripStart = Math.max(0, Math.min(index - Math.floor(stripLimit / 2), entries.length - stripLimit));
  const strip = entries.slice(stripStart, stripStart + stripLimit);

  /** Keep navigation on the current page and stop at either end of the strip. */
  function step(offset: number) {
    const next = entries[index + offset];
    if (next) onSelect(next);
  }

  /** Direction keys are local to the overlay and leave normal buttons accessible. */
  function browse(event: KeyboardEvent<HTMLDivElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    step(event.key === 'ArrowLeft' ? -1 : 1);
  }

  /** Capture a horizontal swipe in the image area without consuming vertical touch movement. */
  function startGesture(event: PointerEvent<HTMLDivElement>) {
    if (!event.isPrimary || event.pointerType === 'mouse' || (event.target as Element).closest('button')) return;
    gesture.current = { x: event.clientX, y: event.clientY, id: event.pointerId };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  /** Ignore taps, vertical drags, second fingers and cancelled gestures. */
  function finishGesture(event: PointerEvent<HTMLDivElement>) {
    const start = gesture.current;
    if (!start || start.id !== event.pointerId) return;
    gesture.current = null;
    const delta = event.clientX - start.x;
    if (Math.abs(delta) > Math.max(swipeThreshold, Math.abs(event.clientY - start.y) * 1.3)) {
      step(delta > 0 ? -1 : 1);
    }
  }

  const descriptor = entry && [kind === 'video' ? '视频封面' : '图片', entry.size == null ? '' : formatBytes(entry.size)]
    .filter(Boolean).join(' · ');
  return <Dialog.Root open={Boolean(entry)} onOpenChange={open => { if (!open) onClose(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-quicklook-overlay" />
      <Dialog.Content className="nfc-quicklook-dialog" onKeyDown={browse}
        onOpenAutoFocus={event => { event.preventDefault(); closer.current?.focus({ preventScroll: true }); }}
        onCloseAutoFocus={event => { event.preventDefault(); gesture.current = null; restoreFocus(); }}>
        <header className="nfc-quicklook-heading">
          <span className="nfc-quicklook-grip" aria-hidden="true" />
          {kind === 'video' ? <Film size={18} aria-hidden="true" /> : <ConsoleIcon name="image" size={18} />}
          <div className="nfc-quicklook-heading-copy">
            <Dialog.Title title={entry?.name}>{entry?.name ?? '快速查看'}</Dialog.Title>
            <Dialog.Description>{descriptor}</Dialog.Description>
          </div>
          {entry && <span className="nfc-quicklook-index" aria-live="polite">{index + 1} / {entries.length}</span>}
          <Dialog.Close asChild>
            <button type="button" ref={closer} className="nfc-quicklook-control" aria-label="关闭快览">
              <ConsoleIcon name="x" size={18} />
            </button>
          </Dialog.Close>
        </header>
        {entry && <div className="nfc-quicklook-media" onPointerDown={startGesture} onPointerUp={finishGesture}
          onPointerCancel={() => { gesture.current = null; }}>
          <MediaThumbnail path={entry.path} kind={kind ?? 'file'} size="cover" />
          <p className="nfc-quicklook-unavailable" role="status">此文件没有可用缩略图</p>
          <button type="button" className="nfc-quicklook-control is-previous" onClick={() => step(-1)}
            aria-label="上一项" disabled={index === 0}><ConsoleIcon name="arrow-left" size={16} /></button>
          <button type="button" className="nfc-quicklook-control is-next" onClick={() => step(1)}
            aria-label="下一项" disabled={index === entries.length - 1}><ConsoleIcon name="arrow-right" size={16} /></button>
          {kind === 'video' && <span className="nfc-quicklook-video-mark"><Film size={14} aria-hidden="true" />视频封面</span>}
        </div>}
        {entry && <div className="nfc-quicklook-strip" role="group" aria-label="当前页缩略图">
          {strip.map(candidate => <button type="button" key={candidate.path} title={candidate.name}
            aria-label={candidate.name} aria-pressed={entry.path === candidate.path} onClick={() => onSelect(candidate)}>
            <MediaThumbnail path={candidate.path} kind={mediaThumbnailKind(candidate.path) ?? 'file'} size="small" />
          </button>)}
        </div>}
        <footer className="nfc-quicklook-footer">
          <span className="nfc-quicklook-key-hints"><kbd>←</kbd> <kbd>→</kbd> 切换文件 <kbd>Esc</kbd> 返回当前文件</span>
          <span className="nfc-quicklook-touch-hints">左右滑动切换 · 关闭后返回当前文件</span>
          <span className="nfc-quicklook-caption">按现有缩略图放大查看</span>
        </footer>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
