import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { directoryHistoryKey, filesystemApi } from '../../api/filesystem';
import { useAuth } from '../../contexts/AuthContext';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { MediaThumbnail } from '../../components/ui/MediaThumbnail';
import { useDisplayPreferences } from '../../contexts/DisplayPreferencesContext';

/** Only load the open collection. The destination preselects a directory for review. */
export function DirectoryShelf() {
  const { user } = useAuth();
  const [tab, setTab] = useState<'recent' | 'favorites'>('recent');
  const { showThumbnails } = useDisplayPreferences();
  const recent = useQuery({
    queryKey: directoryHistoryKey('recent', user?.id, 8), queryFn: () => filesystemApi.listRecent(8), enabled: tab === 'recent',
  });
  const favorites = useQuery({
    queryKey: directoryHistoryKey('favorites', user?.id), queryFn: filesystemApi.listFavorites, enabled: tab === 'favorites',
  });
  const result = tab === 'recent' ? recent : favorites;
  const folders = result.data?.items.slice(0, 8) ?? [];
  return <section className="nfc-studio-shelf" aria-labelledby="studio-shelf-title">
    <div className="nfc-studio-section-heading">
      <h2 id="studio-shelf-title">我的目录</h2>
      <div className="nfc-studio-segment" data-source={tab} role="group" aria-label="目录来源">
        <button type="button" aria-pressed={tab === 'recent'} onClick={() => setTab('recent')}>最近使用</button>
        <button type="button" aria-pressed={tab === 'favorites'} onClick={() => setTab('favorites')}>收藏</button>
      </div>
    </div>
    {result.isPending ? <p className="nfc-studio-shelf-state" role="status">正在读取目录…</p> :
      result.isError ? <p className="nfc-studio-shelf-state" role="alert">目录暂时无法读取。
        <button type="button" onClick={() => { void result.refetch(); }}>重试</button></p> :
      folders.length === 0 ? <div className="nfc-studio-shelf-state">
        <ConsoleIcon name="folder-open" size={22} />
        <span>{tab === 'recent' ? '选过的目录会出现在这里' : '在目录选择器中点星标即可收藏'}</span>
        <Link to="/batch?operation=media-organize">选择目录</Link>
      </div> : <ul className={'nfc-studio-folders' + (showThumbnails ? '' : ' is-compact')}>
        {folders.map(item => {
          const name = ('label' in item && typeof item.label === 'string' && item.label) ||
            item.path.split('/').filter(Boolean).pop() || item.path;
          const contents = <>
            {item.exists ? <MediaThumbnail path={item.path} kind="directory" size={showThumbnails ? 'cover' : 'small'} /> :
              <span className={`nfc-media-thumbnail ${showThumbnails ? 'is-cover is-unavailable' : 'is-icon'}`} aria-hidden="true">
                <ConsoleIcon name="folder" size={18} />
              </span>}
            <span className="nfc-studio-folder-info"><strong>{name}</strong><small>{item.path}</small></span>
            <ConsoleIcon name={item.exists ? 'chevron-right' : 'info'} size={15} />
          </>;
          return <li key={item.path}>{item.exists
            ? <Link to={'/batch?' + new URLSearchParams({ operation: 'media-organize', directory: item.path })}
                title={item.path} aria-label={'核对整理目录 ' + item.path}>{contents}</Link>
            : <div className="is-unavailable" title="目录当前不可用">{contents}<small>目录不可用</small></div>}</li>;
        })}
      </ul>}
  </section>;
}
