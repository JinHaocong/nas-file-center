import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { splitDirectoryPathLines, buildDirectoryBreadcrumb } from '../src/components/DirectoryPicker/path_model';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 DirectoryPicker input and path breadcrumbs', () => {
  test('normalizes multiple manually supplied roots without swallowing an unfinished line', () => {
    assert.deepEqual(splitDirectoryPathLines(' /data/Movies \r\n\n /data/Photos  \n '),
      ['/data/Movies', '/data/Photos']);
    assert.deepEqual(splitDirectoryPathLines(' \n '), []);
    const picker = read('src/components/DirectoryPicker/DirectoryPicker.tsx');
    assert.match(picker, /setManualDraft\(text\)/);
    assert.match(picker, /splitDirectoryPathLines\(text\)/);
    assert.match(picker, /onChange\?\.\(splitDirectoryPathLines\(text\)\)/);
  });

  test('keeps root containment at segment boundaries, choosing the deepest managed root', () => {
    assert.deepEqual(buildDirectoryBreadcrumb('/data/media/Films/2026', ['/data', '/data/media']), {
      baseRoot: '/data/media',
      segments: [
        { name: 'Films', path: '/data/media/Films' },
        { name: '2026', path: '/data/media/Films/2026' },
      ],
    });
    assert.equal(buildDirectoryBreadcrumb('/database/photo', ['/data']), null);
    assert.equal(buildDirectoryBreadcrumb('/data/../etc', ['/data']), null);
    assert.equal(buildDirectoryBreadcrumb('/elsewhere', ['/data']), null);
    assert.equal(buildDirectoryBreadcrumb('/data', []), null);
    assert.deepEqual(buildDirectoryBreadcrumb('/Movies', ['/']), {
      baseRoot: '/', segments: [{ name: 'Movies', path: '/Movies' }],
    });
  });

  test('uses native controlled fields, accessible actions, and keeps modal API contract', () => {
    const source = read('src/components/DirectoryPicker/DirectoryPicker.tsx');
    for (const name of [
      '<ConsoleButton', '<ConsoleIcon', '<CodePath',
      '<DirectoryPickerModal', 'selectedValues={currentValues}',
      'multiple={multiple}', 'initialPath={singleValue || undefined}',
      "aria-label=\"目录路径\"", 'aria-label="清空目录路径"',
      'aria-label="手动多行目录路径"', 'disabled={disabled}',
      "onChange?.(Array.isArray(selected) ? selected[0] || '' : selected)",
      '高级：手动多行输入路径',
    ]) assert.ok(source.includes(name), name);
    assert.doesNotMatch(source, /from ['"]antd['"]|@ant-design\/icons|<Input\b|<Button\b/);
  });

  test('breadcrumb switches only between server-reported allowed roots', () => {
    const source = read('src/components/DirectoryPicker/PathBreadcrumb.tsx');
    assert.match(source, /buildDirectoryBreadcrumb\(currentPath, allowedRoots\)/);
    assert.match(source, /<nav className="nfc-path-breadcrumb/);
    assert.match(source, /aria-label="切换允许的根目录"/);
    assert.match(source, /onNavigate\(event.target.value\)/);
    assert.doesNotMatch(source, /from ['"]antd['"]|@ant-design\/icons|<Dropdown\b/);
    const modal = read('src/components/DirectoryPicker/DirectoryPickerModal.tsx');
    for (const token of ['dirData?.allowed_roots || []', 'onNavigate={handleNavigate}', 'filesystemApi.listDirectory', 'filesystemApi.listFavorites', 'filesystemApi.listRecent']) {
      assert.ok(modal.includes(token), token);
    }
  });

  test('CSS themes and mobile view are imported without removing existing portal chrome', () => {
    const css = read('src/styles/console-v2-directory-picker.css');
    const main = read('src/main.tsx');
    for (const token of ['nfc-v2-directory-picker', 'nfc-v2-path-breadcrumb',
      'var(--nfc-surface-1)', 'var(--nfc-text)', '@media (max-width: 767px)',
      ':focus-visible', 'prefers-reduced-motion']) assert.ok(css.includes(token), token);
    assert.ok(main.includes("import './styles/console-v2-directory-picker.css';"));
  });
});
