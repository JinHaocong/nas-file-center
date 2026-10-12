import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { RenameProposal } from '../src/types';
import {
  DEFAULT_ADVANCED_RENAME_DRAFT, buildAdvancedRenameRequest, canGenerateAdvancedRenamePlan,
} from '../src/utils/advancedRenameSafety';
const read = (p: string) => readFileSync(resolve(process.cwd(),p), 'utf8');
const draft = { ...DEFAULT_ADVANCED_RENAME_DRAFT, paths: ['/nas/pics'] };
const safe: RenameProposal = { source: '/nas/pics/a.webp', target: '/nas/pics/a.jpg', conflict: false };

describe('Console v2 Advanced Regex Rename native UI', () => {
  test('legacy preview payload preserves regex, extension, prefix, suffix and parent defaults', () => {
    assert.deepEqual(buildAdvancedRenameRequest(draft), {
      paths: ['/nas/pics'], regex_pattern: null, regex_replacement: '',
      prefix: '', suffix: '', number_start: null, number_width: 3,
      include_parent: false, source_extension: '', target_extension: '',
    });
    const custom = buildAdvancedRenameRequest({
      ...draft, regex_pattern: String.raw`^DSC_(\d+)`, regex_replacement: 'Photo_$1',
      source_extension: '.webp', target_extension: '.jpg', prefix: '2026_', suffix: '_done',
      include_parent: true, number_start: '0', number_width: '10',
    });
    assert.equal(custom?.regex_pattern, String.raw`^DSC_(\d+)`);
    assert.equal(custom?.regex_replacement, 'Photo_$1');
    assert.equal(custom?.source_extension, '.webp');
    assert.equal(custom?.target_extension, '.jpg');
    assert.equal(custom?.number_start, 0);
    assert.equal(custom?.number_width, 10);
    assert.equal(custom?.include_parent, true);
  });
  test('no paths or invalid integer numbering fail closed; empty start remains null', () => {
    assert.equal(buildAdvancedRenameRequest(DEFAULT_ADVANCED_RENAME_DRAFT), null);
    for (const invalid of ['-1', '1.5', 'NaN', 'Infinity', '9007199254740992']) {
      assert.equal(buildAdvancedRenameRequest({ ...draft, number_start: invalid }), null, invalid);
    }
    for (const invalid of ['0', '11', '2.1', '', 'bogus']) {
      assert.equal(buildAdvancedRenameRequest({ ...draft, number_width: invalid }), null, invalid);
    }
    assert.equal(buildAdvancedRenameRequest({ ...draft, number_start: '' })?.number_start, null);
  });
  test('path list filters empty entries without silently rewriting literal rules', () => {
    const values = buildAdvancedRenameRequest({
      ...draft, paths: ['', ' /nas/first ', '/nas/second'], prefix: ' a ', regex_replacement: ' ',
    });
    assert.deepEqual(values?.paths, [' /nas/first ', '/nas/second']);
    assert.equal(values?.prefix, ' a ');
    assert.equal(values?.regex_replacement, ' ');
  });
  test('Plan guard requires nonempty current preview and no collision/identity/empty target', () => {
    assert.equal(canGenerateAdvancedRenamePlan([safe], 'abc', false), true);
    assert.equal(canGenerateAdvancedRenamePlan([safe], null, false), false);
    assert.equal(canGenerateAdvancedRenamePlan([], 'abc', false), false);
    assert.equal(canGenerateAdvancedRenamePlan(null, 'abc', false), false);
    assert.equal(canGenerateAdvancedRenamePlan([safe], 'abc', true), false);
    assert.equal(canGenerateAdvancedRenamePlan([{ ...safe, conflict: true }], 'abc', false), false);
    assert.equal(canGenerateAdvancedRenamePlan([{ ...safe, target: safe.source }], 'abc', false), false);
    assert.equal(canGenerateAdvancedRenamePlan([{ ...safe, target: '' }], 'abc', false), false);
  });
  test('native page switches three Rename modes, unmounting the inactive editor', () => {
    const s = read('src/pages/Rename/index.tsx');
    for (const symbol of ['useTitle', 'role="radiogroup"', 'name="rename-mode"',
      '<ImmediateDirectoryRename', '<ImmediateFileRename', '<AdvancedRenameEditor',
      "scope === 'directories'", "scope === 'files'", "'advanced'"]) {
      assert.ok(s.includes(symbol), symbol);
    }
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Select\b|<Segmented\b/);
  });
  test('advanced editor transports unchanged API fields and invalidates stale Preview on input edits', () => {
    const s = read('src/pages/Rename/AdvancedRenameEditor.tsx');
    for (const symbol of [
      'batchApi.previewRename(payload)', 'plansApi.createPlan',
      '<DirectoryPicker multiple', 'buildAdvancedRenameRequest(draft)',
      'activePreviewKey.current = null', 'invalidatePreview();',
      'activePreviewKey.current !== key', 'JSON.stringify(currentPayload) !== activePreviewKey.current',
      'previewGuard.current', 'planGuard.current', 'mountedRef.current',
      "operation: 'rename'", "kind: 'rename'",
      'canGenerateAdvancedRenamePlan', 'getStructuredApiError',
      'role="alert"',
    ]) assert.ok(s.includes(symbol), symbol);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Table\b|<Form\b|<InputNumber\b/);
  });
  test('all eight advanced controls and conversion warning remain in native editor', () => {
    const s = read('src/pages/Rename/AdvancedRenameEditor.tsx');
    for (const key of ['regex_pattern', 'regex_replacement', 'source_extension', 'target_extension',
      'prefix', 'suffix', 'number_start', 'number_width', 'include_parent']) {
      assert.ok(s.includes(key), key);
    }
    for (const symbol of ['不会转换图片格式', 'WebP → JPEG 转码',
      '<ConsolePagination', '<ResponsiveDataView', '<StatusBadge',
      'nfc-rename-proposal-mobile-card', '<ConsoleEmpty', '<CodePath',
      'getPaginationState', 'visible.map(', 'type="checkbox"', "'number'"]) {
      assert.ok(s.includes(symbol), symbol);
    }
  });
  test('scoped CSS provides dark mode, responsive tap targets, focus and reduced motion', () => {
    const css = read('src/styles/console-v2-advanced-rename.css');
    for (const selector of ['.nfc-v2-rename-mode', '.nfc-v2-advanced-rename-form',
      '.nfc-v2-advanced-rename-warning', '.nfc-v2-advanced-rename-table',
      '.nfc-v2-advanced-rename-mobile', "[data-theme='dark']", ':focus-visible',
      '@media (max-width:767px)', 'min-height:44px', '@media (prefers-reduced-motion:reduce)']) {
      assert.ok(css.includes(selector), selector);
    }
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-advanced-rename.css';"));
  });
});
