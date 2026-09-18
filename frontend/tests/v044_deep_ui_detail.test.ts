import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.4 deep UI detail and mobile system', () => {
  test('desktop shell keeps navigation viewport-bound while main content owns scrolling', () => {
    const css = read('src/index.css');
    assert.match(css, /\.nfc-app-main\s*\{[^}]*overflow-y:\s*auto/s);
    assert.match(css, /\.nfc-sidebar\.nfc-sidebar\s*\{[^}]*height:\s*calc\(100dvh - 24px\)/s);
    assert.match(css, /\.nfc-sidebar-menu\s*\{[^}]*overflow-y:\s*auto/s);
  });

  test('shared overlays have a mobile full-screen treatment', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('.nfc-overlay-drawer .ant-drawer-content-wrapper'));
    assert.ok(css.includes('.nfc-overlay-modal .ant-modal-content'));
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-overlay-drawer \.ant-drawer-content-wrapper[\s\S]*width:\s*100vw/s);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-overlay-modal[\s\S]*calc\(100vw - 12px\)/s);
  });

  test('task logs use a dedicated mobile card view instead of the desktop table', () => {
    const source = read('src/components/tasks/TaskLogTable.tsx');
    assert.match(source, /useResponsive/);
    assert.match(source, /nfc-task-log-mobile-list/);
    assert.match(source, /nfc-task-log-mobile-card/);
  });

  test('task detail drawer has semantic sections instead of inline layout chrome', () => {
    const source = read('src/components/tasks/TaskDetailDrawer.tsx');
    assert.match(source, /nfc-task-detail-drawer/);
    assert.match(source, /nfc-overlay-section/);
    assert.match(source, /nfc-code-block/);
  });

  test('plan and workflow drawers are mobile-responsive', () => {
    const journal = read('src/pages/Plans/OperationJournalDrawer.tsx');
    const stale = read('src/components/plans/StaleRebuildDrawer.tsx');
    const revisions = read('src/components/workflows/RevisionDrawer.tsx');
    assert.match(journal, /nfc-operation-journal-drawer/);
    assert.match(stale, /nfc-stale-rebuild-drawer/);
    assert.match(revisions, /nfc-revision-drawer/);
    assert.match(revisions, /nfc-code-block/);
  });

  test('every major right-side route has an explicit page identity class', () => {
    const expected = new Map([
      ['src/pages/Dashboard/index.tsx', 'nfc-dashboard-page'],
      ['src/pages/Indexes/index.tsx', 'nfc-indexes-page'],
      ['src/pages/Scans/index.tsx', 'nfc-scans-page'],
      ['src/pages/PathMatch/index.tsx', 'nfc-path-match-page'],
      ['src/pages/Rename/index.tsx', 'nfc-rename-page'],
      ['src/pages/Batch/index.tsx', 'nfc-batch-page'],
      ['src/pages/Organizer/index.tsx', 'nfc-organizer-page'],
      ['src/pages/Workflows/WorkflowList.tsx', 'nfc-workflows-page'],
      ['src/pages/Plans/index.tsx', 'nfc-plans-page'],
      ['src/pages/Quarantine/index.tsx', 'nfc-quarantine-page'],
      ['src/pages/Tasks/index.tsx', 'nfc-tasks-page'],
      ['src/pages/Audit/index.tsx', 'nfc-audit-page'],
      ['src/pages/Settings/index.tsx', 'nfc-system-controls-page'],
      ['src/pages/Scans/ScanDetail.tsx', 'nfc-scan-detail-page'],
      ['src/pages/Scans/AdvancedDedupePage.tsx', 'nfc-advanced-dedupe-page'],
      ['src/pages/Plans/PlanDetail.tsx', 'nfc-plan-detail-page'],
      ['src/pages/Workflows/WorkflowBuilder.tsx', 'nfc-workflow-builder-page'],
      ['src/pages/Organizer/ProfilePreview.tsx', 'nfc-organizer-preview-page'],
    ]);
    for (const [path, className] of expected) {
      assert.ok(read(path).includes(className), `${path} should contain ${className}`);
    }
  });

  test('mobile controls and forms use touch-safe sizing', () => {
    const css = read('src/index.css');
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-operations-page \.ant-btn[\s\S]*min-height:\s*44px/s);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-operations-page \.ant-input[\s\S]*min-height:\s*44px/s);
  });
});
