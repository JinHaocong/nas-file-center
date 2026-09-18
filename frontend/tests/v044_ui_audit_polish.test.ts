import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.4 UI audit polish', () => {
  test('advanced dedupe internals use the shared product surface system', () => {
    assert.match(read('src/components/dedupe/DedupeExplainDrawer.tsx'), /nfc-dedupe-explain-drawer/);
    assert.match(read('src/components/dedupe/DedupeIdentitySafetyPanel.tsx'), /nfc-dedupe-identity-panel/);
    assert.match(read('src/components/dedupe/DedupePreviewSummaryPanel.tsx'), /nfc-dedupe-summary-panel/);
    assert.match(read('src/components/dedupe/DedupeScorerConfigEditor.tsx'), /nfc-dedupe-scorer-editor/);
  });

  test('workflow embedded editors use semantic responsive containers', () => {
    assert.match(read('src/components/workflows/FilterBuilder.tsx'), /nfc-filter-builder/);
    assert.match(read('src/components/workflows/OrganizerStepEditor.tsx'), /nfc-organizer-step-editor/);
    assert.match(read('src/components/workflows/CompletedScanPicker.tsx'), /nfc-completed-scan-picker/);
  });

  test('task progress and directory breadcrumb have reusable semantic chrome', () => {
    assert.match(read('src/components/tasks/TaskProgress.tsx'), /nfc-task-progress/);
    assert.match(read('src/components/DirectoryPicker/PathBreadcrumb.tsx'), /nfc-path-breadcrumb/);
  });

  test('legacy cleanup and organizer import use the current overlay/panel system', () => {
    assert.match(read('src/components/plans/LegacyPlanCleanup.tsx'), /nfc-legacy-plan-cleanup/);
    assert.match(read('src/pages/Organizer/ProfileList.tsx'), /nfc-overlay-modal nfc-organizer-import-modal/);
  });

  test('header status badges no longer depend on inline visual chrome', () => {
    const safe = read('src/components/SafeModeBadge.tsx');
    const worker = read('src/components/WorkerStatusBadge.tsx');
    assert.match(safe, /nfc-header-status-badge/);
    assert.match(worker, /nfc-header-status-badge/);
    assert.doesNotMatch(safe, /style=\{\{/);
    assert.doesNotMatch(worker, /style=\{\{/);
  });

  test('mobile audit styles explicitly cover scorer, filter builder, scan picker and task progress', () => {
    const css = read('src/index.css');
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-dedupe-scorer-editor/s);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-filter-builder/s);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-completed-scan-picker/s);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-task-progress/s);
  });

  test('workflow editors and mobile navigation keep visual layout in semantic CSS', () => {
    const scan = read('src/components/workflows/ScanStepEditor.tsx');
    const move = read('src/components/workflows/MoveStepEditor.tsx');
    const utility = read('src/components/workflows/SingleChildWrapperCollapseStepEditor.tsx');
    const nav = read('src/components/layout/ResponsiveNav.tsx');
    const css = read('src/index.css');

    assert.match(scan, /nfc-workflow-full-control/);
    assert.match(move, /nfc-workflow-full-control/);
    assert.match(utility, /nfc-workflow-field-spaced/);
    assert.doesNotMatch(scan, /style=\{\{/);
    assert.doesNotMatch(move, /style=\{\{/);
    assert.doesNotMatch(utility, /style=\{\{/);
    assert.doesNotMatch(nav, /styles=\{\{/);
    assert.match(css, /\.nfc-mobile-nav-drawer \.ant-drawer-body\s*\{[^}]*padding:\s*0/s);
  });

});
