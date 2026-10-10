import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  initialDirectorySelection, toggleDirectorySelection, resolveDirectorySelection,
  isWithinDirectoryRoots,
} from '../src/components/DirectoryPicker/selection_model';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 Radix directory browser migration', () => {
  test('single and multiple selections preserve fallback and clearing semantics', () => {
    assert.deepEqual(initialDirectorySelection([' /data/A ', '/data/A', '/data/B'], true), ['/data/A', '/data/B']);
    assert.deepEqual(initialDirectorySelection(['/data/A', '/data/B'], false), ['/data/A']);
    assert.deepEqual(toggleDirectorySelection(['/data/A'], '/data/B', true), ['/data/A', '/data/B']);
    assert.deepEqual(toggleDirectorySelection(['/data/A', '/data/B'], '/data/A', true), ['/data/B']);
    assert.deepEqual(toggleDirectorySelection(['/data/A'], '/data/B', false), ['/data/B']);
    assert.deepEqual(resolveDirectorySelection([], '/data', true), ['/data']);
    assert.equal(resolveDirectorySelection([], '/data', false), '/data');
    assert.equal(resolveDirectorySelection([], '', false), null);
  });

  test('client guard checks segment containment and rejects traversal; server is still authoritative', () => {
    assert.equal(isWithinDirectoryRoots('/data/Movies', ['/data']), true);
    assert.equal(isWithinDirectoryRoots('/database', ['/data']), false);
    assert.equal(isWithinDirectoryRoots('/data/../etc', ['/data']), false);
    assert.equal(isWithinDirectoryRoots('data', ['/data']), false);
    assert.equal(isWithinDirectoryRoots('/anywhere', ['/']), true);
    assert.equal(isWithinDirectoryRoots('/data', []), false);
  });

  test('modal keeps browse, favorites, recents, server pagination and safe cancellation', () => {
    const content = read('src/components/DirectoryPicker/DirectoryPickerModal.tsx');
    for (const marker of [
      "import * as Dialog from '@radix-ui/react-dialog'",
      '<Dialog.Root open={open}', '<Dialog.Content',
      '<ConsoleConfirmDialog', 'nfc-overlay-modal',
      'filesystemApi.listDirectory(', 'filesystemApi.listFavorites()',
      'filesystemApi.listRecent(20)', 'filesystemApi.addFavorite(',
      'filesystemApi.deleteFavorite(id)', 'filesystemApi.recordRecent(paths)',
      'PAGE_SIZE = 100', 'searchQuery', 'setPage(1)',
      '<ConsolePagination', 'onChange={newPage => setPage(newPage)}',
      'dirData?.allowed_roots || []', 'isWithinDirectoryRoots(',
      'confirmingRef.current', 'isConfirming', 'if (!next) cancel()',
      'onPointerDownOutside={event => event.preventDefault()}',
      "onConfirm(selection)", 'onCancel()', 'useResponsive',
      '删除收藏记录，不会删除 NAS 上的目录或文件',
      'onEscapeKeyDown',
    ]) assert.ok(content.includes(marker), marker);
    assert.doesNotMatch(content, /from ['"]antd['"]|@ant-design\/icons|<Modal\b|<Popconfirm\b|message\./);
  });

  test('scan outer dialog is Radix so nested picker keeps consistent focus layer', () => {
    const scan = read('src/components/scans/ScanCreateModal.tsx');
    assert.match(scan, /<Dialog.Root open=\{open\}/);
    assert.match(scan, /<Dialog.Content/);
    assert.doesNotMatch(scan, /from ['"]antd['"]|<Modal\b/);
    for (const marker of [
      'createMutation.isPending', 'onEscapeKeyDown',
      'onPointerDownOutside', 'toScanCreatePayload(values)',
      'queryClient.invalidateQueries', "navigate('/scans/' + res.scan_job_id)",
    ]) assert.ok(scan.includes(marker), marker);
  });

  test('portal CSS handles dark mode, small screens, keyboard focus and is registered', () => {
    const css = read('src/styles/console-v2-directory-modal.css');
    const main = read('src/main.tsx');
    const scanCss = read('src/styles/console-v2-scan-create.css');
    for (const marker of [
      '.nfc-v2-directory-dialog', '.nfc-v2-directory-overlay',
      "[data-theme='dark']", '@media (max-width: 767px)',
      ':focus-visible', 'prefers-reduced-motion', 'overscroll-behavior',
    ]) assert.ok(css.includes(marker), marker);
    assert.ok(main.includes("import './styles/console-v2-directory-modal.css';"));
    assert.ok(scanCss.includes('.nfc-v2-scan-create-modal'));
    assert.doesNotMatch(scanCss, /\.ant-modal-content/);
  });
});
