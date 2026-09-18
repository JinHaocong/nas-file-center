import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.0 C5B file tools surfaces contract', () => {
  test('Batch uses product form surfaces while preserving operation payload semantics', () => {
    const source = read('src/pages/Batch/index.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar']) {
      assert.match(source, new RegExp(symbol));
    }
    assert.match(source, /nfc-batch-operation-grid/);
    assert.match(source, /kind:\s*`batch-\$\{op\}`/);
    assert.match(source, /operation:\s*op/);
    assert.match(source, /value=["']hardlink["'][^\n]*disabled/);
    assert.match(source, /value=["']reflink["'][^\n]*disabled/);
    assert.match(source, /Quarantine|隔离/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Path Match has responsive preview cards and preserves keep-first quarantine-plan semantics', () => {
    const source = read('src/pages/PathMatch/index.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar', 'ResponsiveDataView', 'CodePath', 'StatusBadge']) {
      assert.match(source, new RegExp(symbol));
    }
    assert.match(source, /nfc-path-match-mobile-card/);
    assert.match(source, /previewPathMatch/);
    assert.match(source, /roots\.length < 2/);
    assert.match(source, /const keep = g\.members\[0\]\.path/);
    assert.match(source, /operation:\s*['"]quarantine['"]/);
    assert.match(source, /kind:\s*['"]path-match-dedupe['"]/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Rename uses responsive preview cards and preserves extension/conflict contracts', () => {
    const source = read('src/pages/Rename/index.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar', 'ResponsiveDataView', 'CodePath', 'StatusBadge']) {
      assert.match(source, new RegExp(symbol));
    }
    assert.match(source, /nfc-rename-proposal-mobile-card/);
    for (const semantic of [
      'source_extension: values.source_extension',
      'target_extension: values.target_extension',
      'hasConflicts',
      'previewRename',
      "kind: 'rename'",
    ]) {
      assert.match(source, new RegExp(semantic.replace(/[.*+?^$()|[\]\\]/g, '\\$&')));
    }
    assert.match(source, /不会转换|不做.*转码|仅.*重命名/);
    assert.match(source, /disabled=\{hasConflicts\}/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('C5B CSS defines complex file-tool form and mobile result surfaces', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-batch-operation-grid',
      '.nfc-file-tool-form',
      '.nfc-path-match-mobile-card',
      '.nfc-path-match-member',
      '.nfc-rename-proposal-mobile-card',
      '.nfc-file-tool-result-panel',
    ]) {
      assert.match(css, new RegExp(selector.replace('.', '\\.')));
    }
  });
});
