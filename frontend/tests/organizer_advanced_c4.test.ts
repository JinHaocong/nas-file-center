import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Organizer Advanced Rules C4 frontend contract', () => {
  test('frontend types preserve the advanced profile and staged preview authority', () => {
    const workflowTypes = read('src/types/workflow.ts');
    const rootTypes = read('src/types/index.ts');

    for (const semantic of [
      'OrganizerAdvancedRules',
      'directory_depth',
      'file_numbering',
      'latest_child_prefix',
      'single_child_wrapper_collapse',
      'advanced_rules?: OrganizerAdvancedRules',
      'WorkflowOrganizerSummary',
      'organizer_summary?: WorkflowOrganizerSummary',
      'expected_preview_digest?: string',
    ]) {
      assert.match(workflowTypes, new RegExp(semantic.replace(/[.*+?^$()|[\\]\\\\]/g, '\\$&')));
    }

    for (const semantic of [
      'advanced_rules?: OrganizerAdvancedRules',
      'preview_digest?: string',
      'advanced_enabled?: boolean',
      'structural_required?: boolean',
      'proposal_type:',
      'wrapper_candidates?: number',
      'advanced_changes?: number',
    ]) {
      assert.match(rootTypes, new RegExp(semantic.replace(/[.*+?^$()|[\\]\\\\]/g, '\\$&')));
    }
  });

  test('shared Organizer editor exposes all V1 advanced rules collapsed behind safety validation', () => {
    const source = read('src/components/workflows/OrganizerProfileFields.tsx');

    for (const semantic of [
      "key: 'advanced-rules'",
      'Advanced Rules 使用分阶段安全流程',
      "getAdvancedName('directory_depth'",
      "getAdvancedName('file_numbering'",
      "getAdvancedName('latest_child_prefix'",
      "getAdvancedName('single_child_wrapper_collapse'",
      'advancedRulesEnabled && !recursive',
      "mtimeMode === 'ordered'",
      'MOVE → rmdir_empty',
      '<Collapse',
    ]) {
      assert.match(source, new RegExp(semantic.replace(/[.*+?^$()|[\\]\\\\]/g, '\\$&')));
    }
    assert.doesNotMatch(source, /defaultActiveKey=/);
    assert.doesNotMatch(source, /execute now/i);
  });

  test('standalone Organizer Preview binds Generate to preview digest and stages structural before rename', () => {
    const api = read('src/api/organizerProfiles.ts');
    const source = read('src/pages/Organizer/ProfilePreview.tsx');

    assert.match(api, /expected_preview_digest\?: string/);
    for (const semantic of [
      'result.preview_digest',
      'result.structural_required',
      'summary.advanced_changes',
      'summary.wrapper_candidates',
      'expected_preview_digest: params.expectedPreviewDigest',
      'Stage A Structural Preview',
      'Stage B Rename Preview',
      'Stage B 已锁定',
      '必须重新 Preview',
      'proposal_type',
      'summary!.conflicts === 0',
    ]) {
      assert.match(source, new RegExp(semantic.replace(/[.*+?^$()|[\\]\\\\]/g, '\\$&')));
    }
  });

  test('Workflow Organizer carries organizer preview digest and blocks conflicted staged Generate', () => {
    const source = read('src/pages/Workflows/WorkflowPreviewPanelLegacy.tsx');

    for (const semantic of [
      'previewData.organizer_summary',
      'expected_preview_digest:',
      'organizerSummary.preview_digest',
      'organizerConflicts === 0',
      'Organizer Stage A Structural Preview',
      'Organizer Stage B Rename Preview',
      'Stage B rename/file/prefix 计划已锁定',
      '必须重新 Preview',
    ]) {
      assert.match(source, new RegExp(semantic.replace(/[.*+?^$()|[\\]\\\\]/g, '\\$&')));
    }
  });

  test('profile and workflow snapshot paths preserve advanced rules instead of dropping them', () => {
    const defaults = read('src/utils/organizerDefaults.ts');
    const modal = read('src/pages/Organizer/ProfileFormModal.tsx');
    const workflowEditor = read('src/components/workflows/OrganizerStepEditor.tsx');

    assert.match(defaults, /cloneOrganizerAdvancedRules/);
    assert.match(defaults, /advanced_rules: cloneOrganizerAdvancedRules/);
    assert.match(modal, /advanced_rules: editingProfile\.advanced_rules/);
    assert.match(workflowEditor, /advanced_rules: step\.profile_snapshot\.advanced_rules/);
    assert.match(workflowEditor, /advanced_rules: allValues\.advanced_rules/);
  });

  test('C4 styles cover mobile and dark staged surfaces', () => {
    const css = read('src/styles/pages/organizer.css');

    for (const selector of [
      '.nfc-organizer-advanced-rules',
      '.nfc-organizer-advanced-collapse',
      '.nfc-organizer-preview-digest',
      '.nfc-organizer-stage-alert',
      "[data-theme='dark'] .nfc-organizer-advanced-collapse",
      '@media (max-width: 767px)',
    ]) {
      assert.match(css, new RegExp(selector.replace(/[.*+?^$()|[\\]\\\\]/g, '\\$&')));
    }
  });
});
