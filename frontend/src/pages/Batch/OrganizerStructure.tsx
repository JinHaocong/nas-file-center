import { ConsoleIcon, type ConsoleIconName } from '../../components/ui/ConsoleIcon';
import { commonDirectoryPrefix, relativePathLabel } from '../../components/ui/PathPrefixDisclosure';

import type { MediaBatchPreviewUnit } from '../../api/mediaOrganizerBatch';

interface TreeEntry {
  path: string;
  kind: 'folder' | 'file';
  annotation?: string;
  tone?: 'cleanup' | 'target';
}

interface ChangeFact {
  icon: ConsoleIconName;
  title: string;
  note: string;
}

/** Preserve server-provided names and use the planning unit for relative rows if possible. */
function pathName(path: string) {
  return path.split('/').filter(Boolean).at(-1) ?? path;
}

/** Derive the directory represented by a move or one of its files. */
function representedDirectory(path: string, kind: string): string {
  return kind === 'Directory' ? path : path.slice(0, path.lastIndexOf('/')) || '/';
}

/** Use the shared ancestor when an archive lift sends a directory outside the current unit. */
function treeRoot(unit: string, paths: string[]) {
  if (paths.every(path => path === unit || path.startsWith(unit + '/'))) return unit;
  return commonDirectoryPrefix([unit, ...paths]) ?? '/';
}

/** Show the source and destination as small labelled trees of reported paths. */
function DirectoryTree({ root, entries, target = false }: {
  root: string; entries: TreeEntry[]; target?: boolean;
}) {
  const visible = entries.filter(entry => entry.path !== root).slice(0, 7);
  const remaining = entries.length - visible.length - Number(entries.some(entry => entry.path === root));
  return <section className={'nfc-organizer-structure-side' + (target ? ' is-target' : '')}
    aria-label={target ? '整理后目录树' : '整理前目录树'}>
    <h5>{target && <ConsoleIcon name="arrow-right" size={14} />}{target ? '整理后' : '整理前'}</h5>
    <ul>
      <li className="nfc-organizer-tree-root">
        <ConsoleIcon name="folder-open" size={13} /><span title={root}>{pathName(root)}</span>
      </li>
      {visible.map(({ path, kind, annotation, tone }) => (
        <li className={tone ? 'is-' + tone : undefined} key={path}>
          <ConsoleIcon name={kind === 'file' ? 'file-text' : 'folder'} size={13} />
          <span title={path}>{relativePathLabel(path, root)}{kind === 'folder' && '/'}</span>
          {annotation && <small>{annotation}</small>}
        </li>
      ))}
    </ul>
    {remaining > 0 && <p>另有 {remaining.toLocaleString()} 项</p>}
  </section>;
}

/** Describe exact structural changes and sizes from the approved preview. */
function changeFacts(unit: MediaBatchPreviewUnit): ChangeFact[] {
  const facts: ChangeFact[] = [];
  const cleanupCount = unit.wrapper_cleanup_count ?? 0;
  const [cleanup] = unit.wrapper_cleanup_paths ?? [];
  const [first, ...more] = unit.preserved_directory_paths ?? [];
  const lift = unit.sample_moves?.some(move => move.kind === 'Directory' && move.source !== move.target);
  const photoBuckets = unit.groups.length > 0 && unit.groups.every(group => /^P(?:_\d+)? \[/.test(group.name));
  const liftedWrapper = cleanupCount === 1 && cleanup && cleanup !== unit.unit && unit.sample_moves?.some(move =>
    move.source.startsWith(cleanup + '/') && move.target.startsWith(unit.unit + '/') &&
    !move.target.startsWith(cleanup + '/'));
  if (cleanupCount > 0) {
    const title = liftedWrapper ? `${pathName(cleanup)}上提` : `预计清理 ${cleanupCount.toLocaleString()} 个目录`;
    facts.push({ icon: 'arrow-up', title, note: liftedWrapper && photoBuckets
      ? '并入作品根的图片桶' : liftedWrapper ? '并入作品根的目标位置' : '整理后清理已清空的来源目录' });
  } else if (lift) {
    facts.push({ icon: 'arrow-up', title: '整体上提目录', note: '保留目录内部结构' });
  }
  if (unit.groups.length > 0) {
    const number = unit.groups.length.toLocaleString();
    const sizes = unit.groups.slice(0, 3).map(group => group.count.toLocaleString() + (photoBuckets ? ' 张' : ' 个文件'));
    facts.push({
      icon: 'layers', title: photoBuckets ? `整理成 ${number} 个图片桶` : `${number} 个目标分类`,
      note: sizes.join(' + ') + (unit.groups.length > sizes.length ? ' …' : ''),
    });
  }
  if (first) {
    facts.push({
      icon: 'lock',
      title: more.length < 3
        ? '保留 ' + [first, ...more].map(path => pathName(path) + '/').join('、')
        : `保留 ${(more.length + 1).toLocaleString()} 个已知分册`,
      note: '分册边界保留',
    });
  }
  if (facts.length < 3 && unit.needed_moves > 0) {
    facts.push({
      icon: 'arrow-right', title: `移动 ${unit.needed_moves.toLocaleString()} 项`,
      note: unit.renamed_count > 0 ? `改名 ${unit.renamed_count.toLocaleString()} 项` : '按预览映射整理',
    });
  }
  return facts;
}

/** Pair actual source locations and configured destinations without guessing missing folders. */
export function OrganizerStructure({ unit }: { unit: MediaBatchPreviewUnit }) {
  if (unit.status !== 'ready' || unit.recycle_reason) return null;
  const before = new Map<string, TreeEntry>();
  const after = new Map<string, TreeEntry>();
  const moves = unit.sample_moves ?? [];
  const unchanged: TreeEntry[] = [];
  for (const move of moves) {
    if (move.source === move.target) {
      if (representedDirectory(move.source, 'file') === unit.unit) {
        unchanged.push({ path: move.source, kind: move.kind === 'Directory' ? 'folder' : 'file', annotation: '原位保留' });
      }
      continue;
    }
    const source = representedDirectory(move.source, move.kind);
    const target = representedDirectory(move.target, move.kind);
    if (source === target) continue;
    before.set(source, { path: source, kind: 'folder' });
    after.set(target, { path: target, kind: 'folder', tone: 'target' });
  }
  for (const path of unit.wrapper_cleanup_paths ?? []) {
    before.set(path, { path, kind: 'folder', annotation: '预计清理', tone: 'cleanup' });
  }
  for (const group of unit.groups) {
    after.set(group.destination, {
      path: group.destination, kind: 'folder',
      annotation: group.count.toLocaleString() + (/^P(?:_\d+)? \[/.test(group.name) ? ' 张' : ' 个文件'), tone: 'target',
    });
  }
  for (const entry of unchanged) {
    before.set(entry.path, entry);
    after.set(entry.path, entry);
  }
  for (const path of unit.preserved_directory_paths ?? []) {
    before.set(path, { path, kind: 'folder', annotation: '分册' });
    after.set(path, { path, kind: 'folder', annotation: '分册保留' });
  }
  if (!before.size && !after.size) return null;
  const facts = changeFacts(unit);

  return <section className="nfc-organizer-structure" aria-label="目录结构变化">
    {facts.length > 0 && <ul className="nfc-organizer-structure-facts" aria-label="整理变更摘要">
      {facts.map(fact => <li key={fact.title}>
        <ConsoleIcon name={fact.icon} size={15} />
        <div><strong>{fact.title}</strong><span>{fact.note}</span></div>
      </li>)}
    </ul>}
    <h4>目录结构</h4>
    <div className="nfc-organizer-structure-pair">
      <DirectoryTree root={treeRoot(unit.unit, [...before.keys()])} entries={[...before.values()]} />
      <DirectoryTree root={treeRoot(unit.unit, [...after.keys()])} entries={[...after.values()]} target />
    </div>
  </section>;
}
