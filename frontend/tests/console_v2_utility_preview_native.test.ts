import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type {
  WorkflowPreviewResponse, WorkflowUtilityCandidate, WorkflowUtilitySummary,
} from '../src/types/workflow';
import {
  initialUtilityCandidateIds, sameUtilityDraftRequest, sanitizeUtilityCandidateIds,
  selectableUtilityCandidateIds, utilityDraftRequest,
} from '../src/utils/workflowUtilityDraft';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const candidate = (id: string, state = 'READY', selectable = true,
  selected = true): WorkflowUtilityCandidate => ({
  candidate_id:id, wrapper_path:'/nas/' + id, child_path:'/nas/' + id + '/child',
  target_path:'/nas/child', state, selectable, selected,
});
const candidates = [
  candidate('ready-a'), candidate('blocked', 'CONFLICT', false),
  candidate('unsupported', 'UNSUPPORTED_FILESYSTEM', false),
  candidate('ready-b', 'READY', true, false), candidate('flagged', 'CONFLICT', true),
];
const summary: WorkflowUtilitySummary = {
  utility_action:'single_child_wrapper_collapse', scope_path:'/nas',
  candidate_count:5, ready_count:2, candidates,
  selected_candidate_ids:['ready-a','blocked','unsupported','flagged','ready-a'],
};
const preview = {
  workflow_id:7, workflow_revision:3, revision:3,
  compile_digest:'a'.repeat(64), utility_summary:summary,
} as WorkflowPreviewResponse;
const readyInput = {
  preview, workflowId:7, revision:3, contextValid:true,
  isDirty:false, isArchived:false, previewPending:false,
  generatePending:false, selectedCandidateIds:['ready-a','ready-b'],
};

describe('Console v2 native Utility Preview Draft authority', () => {
  test('only explicitly selectable READY candidates survive server or user selection', () => {
    assert.deepEqual(selectableUtilityCandidateIds(candidates), ['ready-a','ready-b']);
    assert.deepEqual(initialUtilityCandidateIds(summary), ['ready-a']);
    assert.deepEqual(initialUtilityCandidateIds({
      ...summary, selected_candidate_ids:undefined as unknown as string[],
    }), ['ready-a']);
    assert.deepEqual(sanitizeUtilityCandidateIds(candidates,
      ['blocked','ready-b','flagged','ready-b','unsupported','ready-a']),
      ['ready-b','ready-a']);
    assert.deepEqual(initialUtilityCandidateIds(undefined), []);
    assert.equal(summary.selected_candidate_ids.length, 5);
  });

  test('Draft request preserves preview compile_digest, revision, explicit IDs and trimmed name', () => {
    const data = utilityDraftRequest(readyInput, '  整理草稿  ');
    assert.deepEqual(data, {
      expected_compile_digest:'a'.repeat(64),
      revision:3, selected_candidate_ids:['ready-a','ready-b'], plan_name:'整理草稿',
    });
    assert.equal(utilityDraftRequest(readyInput, '')?.plan_name, undefined);
    assert.deepEqual(readyInput.selectedCandidateIds, ['ready-a','ready-b']);
  });

  test('fail closed on archived/dirty/loading/pending/identity mismatch/empty digest', () => {
    for (const flag of ['isDirty', 'isArchived', 'previewPending', 'generatePending'] as const) {
      assert.equal(utilityDraftRequest({ ...readyInput, [flag]:true }, ''), null, flag);
    }
    assert.equal(utilityDraftRequest({ ...readyInput, contextValid:false }, ''), null);
    assert.equal(utilityDraftRequest({ ...readyInput, workflowId:8 }, ''), null);
    assert.equal(utilityDraftRequest({ ...readyInput, revision:4 }, ''), null);
    assert.equal(utilityDraftRequest({ ...readyInput, preview:null }, ''), null);
    assert.equal(utilityDraftRequest({ ...readyInput,
      preview:{ ...preview, compile_digest:'' } }, ''), null);
    assert.equal(utilityDraftRequest({ ...readyInput, selectedCandidateIds:[] }, ''), null);
    assert.equal(utilityDraftRequest({ ...readyInput,
      selectedCandidateIds:['ready-a','blocked'] }, ''), null);
    assert.equal(utilityDraftRequest({ ...readyInput,
      selectedCandidateIds:['ready-a','ready-a'] }, ''), null);
    assert.equal(utilityDraftRequest({ ...readyInput,
      preview:{ ...preview, workflow_id:8 } }, ''), null);
    assert.equal(utilityDraftRequest({ ...readyInput,
      preview:{ ...preview, workflow_revision:4 } }, ''), null);
  });

  test('confirmation snapshots cannot be silently switched to different evidence', () => {
    const snapshot = utilityDraftRequest(readyInput, '  Draft ');
    assert.equal(sameUtilityDraftRequest(snapshot,
      utilityDraftRequest(readyInput, 'Draft')), true);
    assert.equal(sameUtilityDraftRequest(snapshot,
      utilityDraftRequest(readyInput, 'Changed')), false);
    assert.equal(sameUtilityDraftRequest(snapshot,
      utilityDraftRequest({ ...readyInput, selectedCandidateIds:['ready-a'] }, 'Draft')), false);
    assert.equal(sameUtilityDraftRequest(snapshot,
      utilityDraftRequest({ ...readyInput, preview:{ ...preview,
        compile_digest:'b'.repeat(64) } }, 'Draft')), false);
    assert.equal(sameUtilityDraftRequest(snapshot, null), false);
  });

  test('native preview preserves readonly API, revision, request identity and no runtime root override', () => {
    const s = read('src/pages/Workflows/UtilityWorkflowPreviewPanel.tsx');
    for (const token of [
      'workflowApi.previewWorkflow(targetId, {',
      'revision: targetRevision', 'page: 1', 'page_size: 500',
      'only_changed: false',
      'request.key !== currentContext.current',
      'request.requestId !== previewSequence.current',
      'data.workflow_id !== request.workflowId',
      'data.workflow_revision ?? data.revision',
      'previewSequence.current += 1',
      'setPreviewData(null)', 'setPreviewContext(null)',
      'setSelectedCandidateIds([])',
      'initialUtilityCandidateIds(data.utility_summary)',
      'canPreviewWorkflow(isArchived) && !isDirty',
      'canGenerateDraft(isArchived)',
      'previewMutation.isPending',
      "candidate.state !== 'READY'",
      'sanitizeUtilityCandidateIds(',
      'selectableUtilityCandidateIds(candidates)',
      'UNSUPPORTED_FILESYSTEM', 'UTILITY_MOVE_UNSUPPORTED_FILESYSTEM',
      'RENAME_NOREPLACE', 'no-clobber',
      '<ResponsiveDataView', '<table', 'nfc-utility-candidate-mobile-card',
      '选择全部 READY 候选',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /runtime_inputs\s*:|root_ids\s*:/);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Table\b|<Checkbox\b|<Popconfirm\b/);
  });

  test('Draft only uses immutable confirm snapshot, rejects stale preview on 409, no file ops', () => {
    const s = read('src/pages/Workflows/UtilityWorkflowPreviewPanel.tsx');
    for (const token of [
      '<ConsoleConfirmDialog', 'danger={false}',
      'sameUtilityDraftRequest(confirmation, requestNow)',
      'draftInFlight.current', 'setDraftBusy(true)',
      'selected_candidate_ids: [...(confirmation.selected_candidate_ids || [])]',
      'workflowApi.generatePlan(targetId, snapshot)',
      "structured.code === 'PREVIEW_CHANGED'",
      "current ? { ...current, compile_digest: '' } : null",
      "queryClient.invalidateQueries({ queryKey: ['plansList'] })",
      'onGeneratePlanSuccess(data.plan_id)',
      '批处理计划草稿',
      'Freeze → Validate → Execute',
      '只生成新的 Draft Plan',
      'setConfirmation(null)',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /plansApi\.(freezePlan|validatePlan|executePlan)|unlink|purgePlan|quarantineApi/);
  });

  test('native CSS has mobile/dark/reduced motion, accessible checkboxes and confirmation', () => {
    const css = read('src/styles/console-v2-utility-preview.css');
    for (const token of [
      '.nfc-v2-utility-preview', '.nfc-v2-utility-table',
      '.nfc-v2-utility-mobile', '.nfc-v2-utility-notice',
      '.nfc-v2-utility-confirm', 'focus-visible',
      "data-theme='dark'", 'max-width:767px',
      'min-height:44px', 'prefers-reduced-motion:reduce',
    ]) assert.ok(css.includes(token), token);
    assert.ok(read('src/main.tsx').includes(
      "import './styles/console-v2-utility-preview.css';"));
  });
});
