import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { copyExactText } from '../src/utils/clipboard';
const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');

describe('Console v2 native shared CodePath', () => {
  test('clipboard writes exactly the original server path without normalization', async () => {
    const original = ' /volume1/资料/照片 2026/原片 #1\\(预览).HEIC ';
    const values: string[] = [];
    const result = await copyExactText(original, {
      writer: { writeText: async value => { values.push(value); } },
      fallback: () => { throw new Error('successful writer must not fall back'); },
    });
    assert.equal(result, 'copied');
    assert.deepEqual(values, [original]);
  });

  test('non-secure NAS origin falls back to native selection copy, preserving bytes', async () => {
    const original = '/mnt/data/space & 工程 (final)/file.txt';
    const calls: string[] = [];
    const result = await copyExactText(original, {
      writer: null,
      fallback: text => { calls.push(text); return true; },
    });
    assert.equal(result, 'copied');
    assert.deepEqual(calls, [original]);
  });

  test('blocked clipboard writer can safely fall back; failures are not reported as success', async () => {
    const errors: string[] = [];
    const rejectedWriter = { writeText: async (_: string) => { throw Error('NotAllowedError'); } };
    assert.equal(await copyExactText('/original', {
      writer: rejectedWriter, fallback: text => { errors.push(text); return true; },
    }), 'copied');
    assert.deepEqual(errors, ['/original']);
    assert.equal(await copyExactText('/original', {
      writer: rejectedWriter, fallback: () => false,
    }), 'failed');
    assert.equal(await copyExactText('/original', {
      writer: rejectedWriter, fallback: () => { throw Error('denied'); },
    }), 'failed');
    assert.equal(await copyExactText('/original', { writer: rejectedWriter }), 'failed');
    assert.equal(await copyExactText('/original', { writer: null }), 'unsupported');
  });

  test('empty paths remain placeholders without copy buttons; full text still available on hover', () => {
    const source = read('src/components/ui/CodePath.tsx');
    for (const token of [
      "if (!value)", 'nfc-code-path-empty', '>—</span>', 'title={value}',
      'copyExactText(value', 'navigator.clipboard', 'fallback: copyUsingSelection',
      "document.execCommand('copy')", 'field.select()', 'field.remove()',
      'activeElement.focus()', 'className="nfc-v2-code-path-value"',
      'nfc-code-path-muted', '<button type="button"',
      'aria-label="复制完整路径"', 'aria-live="polite"', 'role="status"',
      "result?.value === value", '请手动选择路径',
      'void copyPath()', '<ConsoleIcon name="copy"',
    ]) assert.ok(source.includes(token), token);
    assert.doesNotMatch(source, /from ['"]antd['"]|@ant-design\/icons|<Text\b|Typography/);
  });

  test('shared paths stay embedded across scan, quarantine, audit, index and dedupe surfaces', () => {
    const sourceFiles = [
      'src/pages/Scans/ScanDetail.tsx',
      'src/pages/Quarantine/index.tsx',
      'src/pages/Audit/index.tsx',
      'src/pages/Indexes/index.tsx',
      'src/components/dedupe/DedupeStorageActionPanel.tsx',
      'src/components/dedupe/DedupeIdentitySafetyPanel.tsx',
    ];
    for (const file of sourceFiles) {
      const source = read(file);
      assert.ok(source.includes('CodePath'), file);
    }
  });

  test('shared path styling covers long names, keyboard, dark theme and touch targets', () => {
    const css = read('src/styles/console-v2-code-path.css');
    const main = read('src/main.tsx');
    for (const token of [
      '.nfc-v2-code-path', '.nfc-v2-code-path-value',
      '.nfc-v2-code-path-copy', '.nfc-v2-code-path-feedback',
      'text-overflow: ellipsis', 'white-space: nowrap', 'user-select: text',
      "[data-theme='dark']", ':focus-visible', '@media (max-width: 767px)',
      'min-height: 44px', 'prefers-reduced-motion: reduce',
    ]) assert.ok(css.includes(token), token);
    assert.ok(main.includes("import './styles/console-v2-code-path.css';"));
  });
});
