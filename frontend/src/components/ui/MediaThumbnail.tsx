import { useEffect, useRef, useState } from 'react';
import { useDisplayPreferences } from '../../contexts/DisplayPreferencesContext';
import { ConsoleIcon } from './ConsoleIcon';

type ThumbnailKind = 'directory' | 'image' | 'video' | 'file';
type ThumbnailSize = 'cover' | 'small';

interface ThumbnailProps {
  path: string;
  kind: ThumbnailKind;
  size?: ThumbnailSize;
  representativeFile?: string;
}

const previewableFile = /\.(?:jpe?g|jfif|png|webp|gif|bmp|tiff?|mp4|m4v|mov|3gp|mkv|webm|avi|m2?ts|ts)$/i;
const waiting = new Set<() => Promise<void>>();
let activeRequests = 0;

/** Limit decoding requests across all lists, including a directory picker open over a page. */
function scheduleVisibleThumbnails() {
  for (const work of waiting) {
    if (activeRequests >= 2) break;
    waiting.delete(work);
    activeRequests++;
    void work().finally(() => {
      activeRequests--;
      scheduleVisibleThumbnails();
    });
  }
}

/** Accessible names belong to the adjacent filename or directory button. */
function ThumbnailIcon({ kind }: { kind: ThumbnailKind }) {
  return <ConsoleIcon name={kind === 'directory' ? 'folder' : 'file-text'} size={19} />;
}

/** Load only a visible entry and release both queued work and object URLs on navigation. */
function VisibleThumbnail({ url, kind, size }: { url: string; kind: ThumbnailKind; size: ThumbnailSize }) {
  const ref = useRef<HTMLSpanElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const [visible, setVisible] = useState(false);
  const [image, setImage] = useState('');
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!ref.current) return;
    if (typeof IntersectionObserver === 'undefined') {
      setFailed(true);
      return;
    }
    const observer = new IntersectionObserver(([entry]) => {
      setVisible(entry.isIntersecting);
    }, { rootMargin: '48px' });
    observerRef.current = observer;
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || failed) return;
    const controller = new AbortController();
    let objectUrl = '';
    async function load() {
      try {
        const response = await fetch(url, { credentials: 'same-origin', signal: controller.signal });
        if (!response.ok || !response.headers.get('content-type')?.startsWith('image/jpeg')) {
          if (!controller.signal.aborted) setFailed(true);
          return;
        }
        const data = await response.blob();
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(data);
        observerRef.current?.disconnect();
        setImage(objectUrl);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    }
    waiting.add(load);
    scheduleVisibleThumbnails();
    return () => {
      waiting.delete(load);
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setImage('');
    };
  }, [url, visible, failed]);

  return (
    <span ref={ref} className={`nfc-media-thumbnail is-${size}${failed ? ' is-unavailable' : ''}`} aria-hidden="true">
      {image ? <img src={image} alt="" decoding="async" onError={() => setFailed(true)} /> : <ThumbnailIcon kind={kind} />}
    </span>
  );
}

/** Display a server-generated thumbnail or a compact file-type icon according to global preferences. */
export function MediaThumbnail({ path, kind, size = 'small', representativeFile }: ThumbnailProps) {
  const { showThumbnails } = useDisplayPreferences();
  if (!showThumbnails || !path.startsWith('/') || (kind !== 'directory' && !previewableFile.test(path))) {
    return <span className="nfc-media-thumbnail is-icon" aria-hidden="true"><ThumbnailIcon kind={kind} /></span>;
  }
  const cover = kind === 'directory' && representativeFile?.startsWith('/') && previewableFile.test(representativeFile)
    ? representativeFile : undefined;
  const params = new URLSearchParams({ path: cover ?? path, kind: kind === 'directory' && !cover ? 'directory' : 'file' });
  const url = '/api/media/thumbnail?' + params.toString();
  return <VisibleThumbnail key={url} url={url} kind={kind} size={size} />;
}

/** A single shared control for both Settings and the organizer gallery. */
export function ThumbnailSwitch() {
  const { showThumbnails, setShowThumbnails } = useDisplayPreferences();
  return (
    <button type="button" role="switch" aria-checked={showThumbnails} className="nfc-thumbnail-switch"
      onClick={() => setShowThumbnails(!showThumbnails)}>
      <span>显示媒体缩略图</span><span className="nfc-thumbnail-track" aria-hidden="true" />
    </button>
  );
}
