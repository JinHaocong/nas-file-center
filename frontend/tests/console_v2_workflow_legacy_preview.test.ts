import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { buildLegacyDraftRequest, sameLegacyDraftRequest } from '../src/utils/workflowLegacyDraft';
import type { WorkflowPreviewResponse } from '../src/types/workflow';
const read = (path: string) => readFileSync(resolve(process.cwd(),path),'utf8');
const preview = {
  workflow_id: 19, workflow_revision: 5, revision: 5,
  compile_digest:'a'.repeat(64), dedupe_summary:{},
  organizer_summary:{ advanced_enabled:true, structural_required:true,
    preview_digest:'b'.repeat(64), summary:{ conflicts:0 } },
} as WorkflowPreviewResponse;
const base = { preview, workflowId:19, revision:5, mode:'file' as const,
  selectedRoots:[2,3], planName:' Draft ', ready:true };
describe('Console v2 legacy Workflow Preview Draft safety', () => {
  test('file Draft preserves revision, digest, validated root IDs, name', () => {
    assert.deepEqual(buildLegacyDraftRequest(base), {
      expected_compile_digest:'a'.repeat(64), expected_preview_digest:undefined,
      revision:5,runtime_inputs:{root_ids:[2,3]},plan_name:'Draft',
    });
    assert.equal(buildLegacyDraftRequest({...base,selectedRoots:[],planName:''})?.runtime_inputs,undefined);
    for (const roots of [[1,-1],[0],[1.5],[1,1],
      Array.from({length:17},(_,i)=>i+1)]) {
      assert.equal(buildLegacyDraftRequest({...base,selectedRoots:roots},),null);
    }
  });
  test('dedupe cannot draft without scan ID or authority summary', () => {
    const valid = { ...base, mode:'dedupe' as const, selectedScanJobId:42 };
    const draft=buildLegacyDraftRequest(valid);
    assert.deepEqual(draft?.runtime_inputs,{scan_job_id:42});
    assert.equal(draft?.expected_compile_digest,preview.compile_digest);
    assert.equal(buildLegacyDraftRequest({...valid,selectedScanJobId:undefined}),null);
    assert.equal(buildLegacyDraftRequest({...valid,selectedScanJobId:0}),null);
    assert.equal(buildLegacyDraftRequest({...valid,selectedScanJobId:3.5}),null);
    assert.equal(buildLegacyDraftRequest({...valid,
      preview:{...preview,dedupe_summary:null}}),null);
  });
  test('organizer Advanced requires separate preview digest and zero blocking conflicts', () => {
    const valid = {...base,mode:'organizer' as const, selectedRoots:[2]};
    assert.equal(buildLegacyDraftRequest(valid)?.expected_preview_digest,'b'.repeat(64));
    assert.equal(buildLegacyDraftRequest({...valid,selectedRoots:[2,3]}),null);
    assert.equal(buildLegacyDraftRequest({...valid,preview:{...preview,
      organizer_summary:{...preview.organizer_summary!,preview_digest:''}}}),null);
    assert.equal(buildLegacyDraftRequest({...valid,preview:{...preview,
      organizer_summary:{...preview.organizer_summary!,summary:{conflicts:1}}}}),null);
  });
  test('changed revision/digest, invalidated preview, dirty or pending readiness reject Draft', () => {
    assert.equal(buildLegacyDraftRequest({...base,ready:false}),null);
    assert.equal(buildLegacyDraftRequest({...base,revision:6}),null);
    assert.equal(buildLegacyDraftRequest({...base,workflowId:20}),null);
    assert.equal(buildLegacyDraftRequest({...base,preview:null}),null);
    assert.equal(buildLegacyDraftRequest({...base,preview:{...preview,compile_digest:''}}),null);
    const draft=buildLegacyDraftRequest(base);
    assert.equal(sameLegacyDraftRequest(draft,buildLegacyDraftRequest(base)),true);
    assert.equal(sameLegacyDraftRequest(draft,buildLegacyDraftRequest({...base,planName:'Other'})),false);
    assert.equal(sameLegacyDraftRequest(draft,buildLegacyDraftRequest({...base,selectedRoots:[2]})),false);
  });
  test('native panel preserves all legacy API contracts and dedicated safety components', () => {
    const s=read('src/pages/Workflows/WorkflowPreviewPanelLegacy.tsx');
    for(const token of [
      'workflowApi.previewWorkflow(snapshot.workflowId',
      'workflowApi.generatePlan(targetId, snapshot)',
      'shouldAcceptWorkflowResponse(', 'latestRequestIdRef.current',
      'transitionPreviewState(', 'normalizeSelectedRoots(', 'computeCanDraft(',
      'buildLegacyDraftRequest(', 'sameLegacyDraftRequest(',
      'computeWorkflowDedupeTableTotal(', 'mapWorkflowPreviewItemsToDedupeRows(',
      '<CompletedScanPicker', '<DedupeIdentitySafetyPanel', '<DedupePreviewSummaryPanel',
      '<DedupePreviewTable', '<DedupeExplainDrawer',
      'DEDUPE_SCAN_NOT_COMPLETED', 'DEDUPE_SCAN_NOT_FOUND',
      'DEDUPE_PREVIEW_CHANGED', 'PREVIEW_CHANGED', 'WORKFLOW_ARCHIVED',
      'organizerStructuralRequired', 'organizerConflicts',
      '<ConsoleConfirmDialog', '<ConsolePagination',
      '<ResponsiveDataView', '<table', 'role="group"',
      'selectedRoots', 'page_size: snapshot.pageSize',
      'runtime_inputs:', 'scan_job_id:', 'root_ids:',
      'Freeze → Validate → Execute',
    ]) assert.ok(s.includes(token),token);
    assert.doesNotMatch(s,/from ['"]antd['"]|@ant-design\/icons|<Table\b|<Popconfirm\b|<Select\b|<Switch\b|<Pagination\b/);
    assert.doesNotMatch(s,/plansApi\.(executePlan|freezePlan|validatePlan)|unlink|quarantineApi\.purge/);
  });
  test('desktop/mobile, dark and keyboard focus styles remain accessible', () => {
    const css=read('src/styles/console-v2-workflow-legacy-preview.css');
    for(const x of ['.nfc-v2-legacy-preview','.nfc-v2-legacy-table',
      '.nfc-v2-legacy-mobile','.nfc-v2-legacy-notice',
      "data-theme='dark'",'max-width:767px','focus-visible',
      'prefers-reduced-motion:reduce','min-height:44px']) assert.ok(css.includes(x),x);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-workflow-legacy-preview.css';"));
  });
});
