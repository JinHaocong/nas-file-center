import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { validateWorkflowStepOrder, getAllowedInsertions } from '../src/utils/workflowTopology.js';
import { createDefaultDedupeScorerConfig, validateScorerConfigForm } from '../src/utils/dedupeConfig.js';

const workflowTypesSource = readFileSync(resolve(process.cwd(), 'src/types/workflow.ts'), 'utf8');
const builderSource = readFileSync(resolve(process.cwd(), 'src/pages/Workflows/WorkflowBuilder.tsx'), 'utf8');
const previewPanelSource = [
  readFileSync(resolve(process.cwd(), 'src/pages/Workflows/WorkflowPreviewPanel.tsx'), 'utf8'),
  readFileSync(resolve(process.cwd(), 'src/pages/Workflows/UtilityWorkflowPreviewPanel.tsx'), 'utf8'),
].join('\n');
const dedupeEditorSource = readFileSync(resolve(process.cwd(), 'src/components/dedupe/DedupeScorerConfigEditor.tsx'), 'utf8');
const explainDrawerSource = readFileSync(resolve(process.cwd(), 'src/components/dedupe/DedupeExplainDrawer.tsx'), 'utf8');
const RECURSIVE_MODE = 'recursive_directory_balanced_by_bytes';

describe('Gate6-B Utility frontend contract', () => {
  const utilityStep: any = { id: 'utility-collapse-1', type: 'single_child_wrapper_collapse', root_id: 7, subpath: 'media/incoming' };
  test('utility is an explicit single-step workflow topology', () => {
    assert.strictEqual(validateWorkflowStepOrder([utilityStep], 'utility' as any).valid, true);
    assert.deepStrictEqual(getAllowedInsertions([utilityStep], 'utility' as any), []);
  });
  test('workflow transport models the frozen utility shape and selection contract', () => {
    assert.match(workflowTypesSource, /WorkflowMode[\s\S]*?'utility'/);
    assert.match(workflowTypesSource, /single_child_wrapper_collapse/);
    assert.match(workflowTypesSource, /root_id:\s*number/);
    assert.match(workflowTypesSource, /subpath\?:\s*string/);
    assert.match(workflowTypesSource, /utility_summary/);
    assert.match(workflowTypesSource, /selected_candidate_ids/);
    assert.match(workflowTypesSource, /utility-live-readonly/);
  });
  test('builder exposes Utility mode backed by managed root plus optional subpath', () => {
    assert.match(builderSource, /value=["']utility["']/);
    assert.match(builderSource, /single_child_wrapper_collapse/);
    assert.match(builderSource, /目录工具流|Utility/);
  });
  test('preview renders utility candidates and Generate sends explicit selected candidate ids', () => {
    assert.match(previewPanelSource, /isUtility/);
    assert.match(previewPanelSource, /utility_summary/);
    assert.match(previewPanelSource, /selectedCandidateIds/);
    assert.match(previewPanelSource, /selected_candidate_ids/);
    assert.match(previewPanelSource, /selectable/);
    assert.match(previewPanelSource, /READY/);
  });
});

describe('Gate6-B Recursive Directory Balance frontend contract', () => {
  test('recursive selection mode validates without changing historical modes', () => {
    const config: any = createDefaultDedupeScorerConfig();
    config.selection_mode = RECURSIVE_MODE;
    assert.strictEqual(validateScorerConfigForm(config).valid, true);
    for (const historicalMode of ['weighted', 'balanced_by_bytes']) {
      const historical: any = createDefaultDedupeScorerConfig();
      historical.selection_mode = historicalMode;
      assert.strictEqual(validateScorerConfigForm(historical).valid, true);
    }
  });
  test('selection labels distinguish scan-root balance from recursive directory balance', () => {
    assert.match(dedupeEditorSource, /Balanced by Scan Root/);
    assert.match(dedupeEditorSource, /Recursive Directory Balanced by Bytes/);
    assert.match(dedupeEditorSource, /recursive_directory_balanced_by_bytes/);
  });
  test('recursive last-file protection is presented as mandatory with no disable transport', () => {
    assert.match(dedupeEditorSource, /Recursive Last-File Protection/);
    assert.match(dedupeEditorSource, /强制|mandatory/i);
    assert.doesNotMatch(dedupeEditorSource, /recursive_last_file_protection_enabled/);
  });
  test('Explain UI exposes recursive bucket, LCA, byte-balance, and protection evidence', () => {
    assert.match(explainDrawerSource, /candidate_balance_bucket/);
    assert.match(explainDrawerSource, /recursive_last_file_protection_reason/);
    assert.match(explainDrawerSource, /bucket_released_bytes_before/);
    assert.match(explainDrawerSource, /bucket_released_bytes_after/);
    assert.match(explainDrawerSource, /\blca\b/);
    assert.match(explainDrawerSource, /spread_before/);
    assert.match(explainDrawerSource, /spread_after/);
  });
});
