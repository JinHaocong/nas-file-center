import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.0 C5A workflows and organizer surfaces contract', () => {
  test('Workflow list uses responsive product primitives and preserves RBAC/archive/revisions', () => {
    const source = read('src/pages/Workflows/WorkflowList.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar', 'ResponsiveDataView', 'StatusBadge']) {
      assert.match(source, new RegExp(symbol));
    }
    assert.match(source, /nfc-workflow-mobile-card/);
    for (const semantic of ['canCreateWorkflow', 'canArchiveWorkflow', 'RevisionDrawer', 'archiveWorkflow', 'includeArchived']) {
      assert.match(source, new RegExp(semantic));
    }
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Workflow builder uses shared surfaces while keeping revision/RBAC/dirty semantics', () => {
    const source = read('src/pages/Workflows/WorkflowBuilder.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar']) {
      assert.match(source, new RegExp(symbol));
    }
    for (const semantic of [
      'parseWorkflowRevisionQuery',
      'expected_current_revision',
      'canSaveRevision',
      'canRollbackWorkflow',
      'canSwitchWorkflowMode',
      'WorkflowPreviewPanel',
      'RevisionDrawer',
      'isDirty',
    ]) {
      assert.match(source, new RegExp(semantic));
    }
    assert.match(source, /nfc-workflow-mode-grid/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Utility workflow preview has mobile candidate cards and keeps compile-digest authority', () => {
    const source = read('src/pages/Workflows/UtilityWorkflowPreviewPanel.tsx');
    for (const symbol of ['DataPanel', 'ActionBar', 'ResponsiveDescriptions', 'ResponsiveDataView', 'CodePath']) {
      assert.match(source, new RegExp(symbol));
    }
    for (const semantic of ['compile_digest', 'selected_candidate_ids', 'PREVIEW_CHANGED', 'canGenerateDraft', 'canPreviewWorkflow']) {
      assert.match(source, new RegExp(semantic));
    }
    assert.match(source, /nfc-utility-candidate-mobile-card/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Organizer shell and profile list use shared responsive surfaces', () => {
    const page = read('src/pages/Organizer/index.tsx');
    const list = read('src/pages/Organizer/ProfileList.tsx');
    assert.match(page, /PageHeader/);
    for (const symbol of ['DataPanel', 'ActionBar', 'ResponsiveDataView', 'CodePath']) {
      assert.match(list, new RegExp(symbol));
    }
    assert.match(list, /nfc-organizer-profile-mobile-card/);
    for (const semantic of ['cloneMutation', 'importMutation', 'deleteMutation', 'handleExport']) {
      assert.match(list, new RegExp(semantic));
    }
    assert.doesNotMatch(list, /<Card\b/);
  });

  test('Organizer preview keeps snapshot/conflict/plan gates and uses mobile proposal cards', () => {
    const source = read('src/pages/Organizer/ProfilePreview.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar', 'MetricCard', 'ResponsiveDataView', 'CodePath', 'StatusBadge']) {
      assert.match(source, new RegExp(symbol));
    }
    for (const semantic of ['snapshot_id', 'summary!.conflicts === 0', 'createPlan', 'include_touch', 'canGeneratePlan']) {
      assert.match(source, new RegExp(semantic.replace(/[.*+?^$()|[\]\\]/g, '\\$&')));
    }
    assert.match(source, /nfc-organizer-proposal-mobile-card/);
    assert.doesNotMatch(source, /<Card\b/);
    assert.doesNotMatch(source, /<Statistic\b/);
  });

  test('C5A CSS defines complex workflow and organizer responsive surfaces', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-workflow-mobile-card',
      '.nfc-workflow-mode-grid',
      '.nfc-workflow-builder-grid',
      '.nfc-utility-candidate-mobile-card',
      '.nfc-organizer-profile-mobile-card',
      '.nfc-organizer-proposal-mobile-card',
      '.nfc-complex-form-panel',
    ]) {
      assert.match(css, new RegExp(selector.replace('.', '\\.')));
    }
  });
});
