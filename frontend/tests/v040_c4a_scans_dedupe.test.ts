import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.0 C4A scans and dedupe surfaces contract', () => {
  test('Scans list uses v0.4.0 data primitives and dedicated mobile cards', () => {
    const source = read('src/pages/Scans/index.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar', 'ResponsiveDataView', 'StatusBadge']) {
      assert.match(source, new RegExp(symbol));
    }
    assert.match(source, /nfc-scan-mobile-card/);
    assert.match(source, /ScanDeleteButton/);
    assert.match(source, /return hasActive \? 3000 : false/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Scan Detail uses responsive descriptions and mobile duplicate-group cards', () => {
    const source = read('src/pages/Scans/ScanDetail.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ResponsiveDescriptions', 'ResponsiveDataView', 'StatusBadge', 'CodePath']) {
      assert.match(source, new RegExp(symbol));
    }
    assert.match(source, /nfc-duplicate-group-mobile-card/);
    assert.match(source, /DedupePlanModal/);
    assert.match(source, /Advanced Dedupe|高级去重/);
    assert.match(source, /ScanDeleteButton/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Advanced Dedupe keeps authority and state-machine semantics while using new surfaces', () => {
    const source = read('src/pages/Scans/AdvancedDedupePage.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar', 'ResponsiveDescriptions', 'StatusBadge']) {
      assert.match(source, new RegExp(symbol));
    }
    for (const semantic of [
      'acceptedPreviewDigest',
      'PREVIEW_CHANGED',
      'expected_preview_digest',
      'canGeneratePlan',
      'DedupeIdentitySafetyPanel',
      'DedupePreviewSummaryPanel',
      'DedupePreviewTable',
      'Freeze -> Validate -> Execute',
    ]) {
      assert.match(source, new RegExp(semantic.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')));
    }
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Dedupe preview renders mobile member cards rather than only a wide table', () => {
    const source = read('src/components/dedupe/DedupePreviewTable.tsx');
    assert.match(source, /ResponsiveDataView/);
    assert.match(source, /nfc-dedupe-member-mobile-card/);
    assert.match(source, /onSelectMember/);
    assert.match(source, /decisionFilter/);
    assert.match(source, /rootFilter/);
  });

  test('C4A CSS defines scan and dedupe mobile surfaces', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-scan-mobile-card',
      '.nfc-duplicate-group-mobile-card',
      '.nfc-duplicate-member-list',
      '.nfc-dedupe-config-actions',
      '.nfc-dedupe-plan-surface',
      '.nfc-dedupe-member-mobile-card',
    ]) {
      assert.match(css, new RegExp(selector.replace('.', '\\.')));
    }
  });
});
