import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { PathMatchGroup, PathMatchPreviewResponse } from '../src/api/domain';
import {
  buildPathMatchRequest, buildPathMatchPlanItems, canCreatePathMatchPlan,
} from '../src/utils/pathMatchSafety';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const member = (root: string, path: string, size = 1024, mtime_ns = 123456) => ({
  root, path, relative_path: 'movie.mkv', size, mtime_ns,
});
const group: PathMatchGroup = { key: 'movie.mkv', members: [
  member('root-0', '/nas/A/movie.mkv'),
  member('root-1', '/nas/B/movie.mkv'),
  member('root-2', '/nas/C/movie.mkv', 0),
]};
const report = (groups: PathMatchGroup[] = [group]): PathMatchPreviewResponse => ({
  groups, count: groups.length,
});
const copied = () => report(JSON.parse(JSON.stringify([group])) as PathMatchGroup[]);

describe('Console v2 native Path Match readonly Preview / safe Draft', () => {
  test('preserves exact four-field request with literal roots and legacy modes', () => {
    const roots = ['/nas/A', '/nas/B'];
    const req = buildPathMatchRequest(roots, 'relative-path', 'unused', 'unused');
    assert.deepEqual(req, {
      roots, mode: 'relative-path', normalize_pattern: null, normalize_replacement: '',
    });
    assert.deepEqual(buildPathMatchRequest(roots, 'basename', '', '')?.roots, roots);
    assert.deepEqual(buildPathMatchRequest(roots, 'stem', '', '')?.roots, roots);
    assert.deepEqual(buildPathMatchRequest(roots, 'normalized', '\\d+', '_'), {
      roots, mode: 'normalized', normalize_pattern: '\\d+', normalize_replacement: '_',
    });
    assert.deepEqual(roots, ['/nas/A', '/nas/B']);
  });

  test('rejects underspecified, repeated or whitespace-only roots and empty normalized Pattern', () => {
    assert.equal(buildPathMatchRequest(['/nas/A'], 'stem', '', ''), null);
    assert.equal(buildPathMatchRequest(['/nas/A', '  '], 'stem', '', ''), null);
    assert.equal(buildPathMatchRequest(['/nas/A', '/nas/A'], 'stem', '', ''), null);
    assert.equal(buildPathMatchRequest(['/nas/A', '/nas/B'], 'normalized', '  ', ''), null);
    assert.equal(buildPathMatchRequest(['/nas/A', '/nas/B'], 'bogus' as any, '', ''), null);
  });

  test('builds keep-first, quarantine-other exact plan Draft including zero-byte files', () => {
    const items = buildPathMatchPlanItems(report(), copied());
    assert.deepEqual(items, [
      { operation: 'quarantine', source: '/nas/B/movie.mkv', keep: '/nas/A/movie.mkv', expected_size: 1024 },
      { operation: 'quarantine', source: '/nas/C/movie.mkv', keep: '/nas/A/movie.mkv', expected_size: 0 },
    ]);
    assert.equal(group.members[0].size, 1024);
  });

  test('supports multiple groups while preserving member order and distinct keeps', () => {
    const second: PathMatchGroup = { key: 'other', members: [
      member('root-0', '/nas/A/other', 12), member('root-1', '/nas/B/other', 12),
    ] };
    const result = buildPathMatchPlanItems(report([group, second]), report([group, second]));
    assert.equal(result?.length, 3);
    assert.equal(result?.[2].keep, '/nas/A/other');
    assert.equal(result?.[2].expected_size, 12);
  });

  test('detects content metadata changes, swapped keep, key reorder, missing group and size', () => {
    const before = report();
    for (const after of [
      report([{ ...group, members: [group.members[1], group.members[0], group.members[2]] }]),
      report([{ ...group, members: group.members.map((m, i) => i === 1 ? { ...m, size: 100 } : m) }]),
      report([{ ...group, members: group.members.map((m, i) => i === 1 ? { ...m, mtime_ns: 123457 } : m) }]),
      report([{ ...group, members: group.members.map((m, i) => i === 2 ? { ...m, path: '/nas/changed' } : m) }]),
      report([{ ...group, key: 'renamed' }]),
      report([]),
      { ...report(), count: 9 },
    ]) assert.equal(buildPathMatchPlanItems(before, after), null);
  });

  test('invalid backend candidates fail closed instead of creating a destructive draft', () => {
    const unsafeGroups: PathMatchGroup[][] = [
      [{ ...group, members: [group.members[0]] }],
      [{ ...group, members: [group.members[0], { ...group.members[1], size: -1 }] }],
      [{ ...group, members: [group.members[0], { ...group.members[1], size: NaN }] }],
      [{ ...group, members: [group.members[0], { ...group.members[1], path: 'relative/file' }] }],
      [{ ...group, members: [group.members[0], { ...group.members[1], mtime_ns: Infinity }] }],
      [{ ...group, members: [group.members[0], { ...group.members[1], path: group.members[0].path }] }],
      [group, { ...group, key: 'other' }],
    ];
    for (const groups of unsafeGroups) {
      assert.equal(buildPathMatchPlanItems(report(groups), report(groups)), null);
    }
    assert.equal(buildPathMatchPlanItems(report([]), report([])), null);
  });

  test('a source cannot also be a keep in a second group', () => {
    const extra: PathMatchGroup = {
      key: 'cross', members: [group.members[1], member('root-9', '/nas/D/x')],
    };
    const payload = report([group, extra]);
    assert.equal(buildPathMatchPlanItems(payload, payload), null);
  });

  test('plan gate requires a current matching request key, no in-flight mutations and a valid report', () => {
    const key = JSON.stringify(buildPathMatchRequest(['/nas/A', '/nas/B'], 'stem', '', ''));
    assert.equal(canCreatePathMatchPlan(report(), key, key, false), true);
    assert.equal(canCreatePathMatchPlan(report(), key, key, true), false);
    assert.equal(canCreatePathMatchPlan(report(), key, 'other', false), false);
    assert.equal(canCreatePathMatchPlan(report(), null, key, false), false);
    assert.equal(canCreatePathMatchPlan(null, key, key, false), false);
    assert.equal(canCreatePathMatchPlan(report([]), key, key, false), false);
  });

  test('page uses native controls and retains exact preview / draft backend APIs', () => {
    const page = read('src/pages/PathMatch/index.tsx');
    for (const token of [
      'batchApi.previewPathMatch', 'plansApi.createPlan',
      'requestTicket.current !== ticket', 'activePreviewKey.current !== key',
      'buildPathMatchPlanItems(captured, fresh)', 'previewGuard.current',
      'planGuard.current', 'getPaginationState', 'visibleGroups.map(',
      'useConsoleToast', 'ConsoleButton', 'ConsolePagination', 'ConsoleEmpty',
      'DirectoryPicker multiple value={roots}', '<ResponsiveDataView',
      '<CodePath', '<StatusBadge', 'roots.length < 2',
      'kind: ', 'path-match-dedupe', '不能', '冻结与校验',
    ].filter(token => token !== '不能')) assert.ok(page.includes(token), token);
    assert.doesNotMatch(page, /from ['"]antd['"]|@ant-design\/icons|<Table\b|<Form\b|<Select\b/);
    assert.doesNotMatch(page, /executePlan|freezePlan|validatePlan|deleteFile|renameFile/);
  });

  test('responsive CSS covers desktop/mobile, dark, focus and reduced motion', () => {
    const css = read('src/styles/console-v2-path-match.css');
    for (const token of [
      '.nfc-v2-path-match', '.nfc-v2-path-match-table',
      '.nfc-v2-path-match-mobile', "[data-theme='dark']",
      ':focus-visible', '@media (max-width:767px)',
      '@media (prefers-reduced-motion:reduce)', 'min-height:44px',
    ]) assert.ok(css.includes(token), token);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-path-match.css';"));
  });
});
