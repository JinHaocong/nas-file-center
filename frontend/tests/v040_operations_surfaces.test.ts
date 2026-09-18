import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.0 C2B operations surfaces contract', () => {
  test('shared operations primitives exist', () => {
    for (const path of [
      'src/components/ui/ActionBar.tsx',
      'src/components/ui/ResponsiveDataView.tsx',
      'src/components/ui/ResponsiveDescriptions.tsx',
      'src/components/ui/CodePath.tsx',
    ]) {
      assert.doesNotThrow(() => read(path), `missing ${path}`);
    }
  });

  test('Task Center uses the v0.4.0 visual layer and mobile data view', () => {
    const source = read('src/pages/Tasks/index.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar', 'ResponsiveDataView', 'StatusBadge']) {
      assert.match(source, new RegExp(symbol));
    }
    assert.match(source, /nfc-task-mobile-card/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Task Center preserves polling, cleanup, detail and delete semantics', () => {
    const source = read('src/pages/Tasks/index.tsx');
    assert.match(source, /return hasActive \? 3000 : false/);
    assert.match(source, /TaskHistoryCleanupModal/);
    assert.match(source, /TaskDeleteButton/);
    assert.match(source, /TaskDetailDrawer/);
    assert.match(source, /WorkerStatusCard/);
    assert.match(source, /setInterval\(\(\) =>/);
  });

  test('Plans list uses responsive operational data view without legacy Card shell', () => {
    const source = read('src/pages/Plans/index.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar', 'ResponsiveDataView', 'StatusBadge']) {
      assert.match(source, new RegExp(symbol));
    }
    assert.match(source, /nfc-plan-mobile-card/);
    assert.match(source, /LegacyPlanCleanup/);
    assert.match(source, /PlanHistoryCleanupModal/);
    assert.match(source, /PlanDeleteButton/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Plan Detail preserves lifecycle and destructive safety while using new primitives', () => {
    const source = read('src/pages/Plans/PlanDetail.tsx');
    for (const symbol of [
      'PageHeader',
      'DataPanel',
      'ActionBar',
      'ResponsiveDataView',
      'ResponsiveDescriptions',
      'CodePath',
      'StatusBadge',
    ]) {
      assert.match(source, new RegExp(symbol));
    }
    for (const semantic of [
      'freezeMutation',
      'validateMutation',
      'executeMutation',
      'PlanDeleteButton',
      'OperationJournalDrawer',
      'StaleRebuildDrawer',
      'Popconfirm',
      'ALLOW_MUTATION=false',
    ]) {
      assert.match(source, new RegExp(semantic));
    }
    assert.match(source, /nfc-plan-item-mobile-card/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('operations CSS supports action bars, descriptions and dedicated mobile cards', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-action-bar',
      '.nfc-responsive-descriptions',
      '.nfc-description-item',
      '.nfc-task-mobile-card',
      '.nfc-plan-mobile-card',
      '.nfc-plan-item-mobile-card',
      '.nfc-lifecycle-strip',
      '.nfc-code-path',
    ]) {
      assert.match(css, new RegExp(selector.replace('.', '\\.')));
    }
  });
});
