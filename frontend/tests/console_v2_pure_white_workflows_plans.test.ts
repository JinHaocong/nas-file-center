import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const workflow = read('src/styles/console-v2-workflow-builder.css');
const revisions = read('src/styles/console-v2-workflow-revisions.css');
const plans = read('src/styles/console-v2-plan-detail.css');

describe('Pure White Stage 3A Workflow and Plan detail', () => {
  test('Workflow Builder uses charcoal on white and deliberate dark neutral surfaces', () => {
    assert.match(workflow, /--nfc-wf-paper:\s*#fff;\s*--nfc-wf-text:\s*#20201f;\s*--nfc-wf-muted:\s*#696965;/);
    assert.match(workflow, /--nfc-wf-line:\s*#eaeae7;\s*--nfc-wf-accent:\s*#252525;/);
    assert.match(workflow, /\[data-theme='dark'\] \.nfc-v2-workflow-state\s*\{[^}]*--nfc-wf-paper:\s*#242422;[^}]*--nfc-wf-accent:\s*#e9e9e6;/);
    assert.match(workflow, /\.nfc-workflow-builder-page\s*\{\s*--nfc-info-soft:\s*var\(--nfc-accent-soft\);\s*\}/);
    assert.doesNotMatch(workflow, /#2878ef|#83b5ff|#1a2434|#36435a/);
  });

  test('Workflow form stays responsive, accessible and warning/error semantics are not removed', () => {
    for (const marker of [
      '.nfc-v2-workflow-mode-choice:focus-within',
      '.nfc-v2-step-menu-item:focus-visible',
      '.nfc-v2-workflow-field > input[aria-invalid=',
      '.nfc-v2-workflow-notice.is-warning',
      '.nfc-v2-workflow-notice.is-error',
      '@media (max-width: 767px)',
      '@media (prefers-reduced-motion: reduce)',
    ]) assert.ok(workflow.includes(marker), marker);
  });

  test('Workflow revision inspect portal has neutral theme parity and row keyboard focus', () => {
    assert.match(revisions, /\.nfc-v2-revision-inspect\s*\{[^}]*--v2-paper:\s*#ffffff;[^}]*--v2-indigo:\s*#252525;/);
    assert.match(revisions, /\[data-theme='dark'\] \.nfc-v2-revision-inspect\s*\{[^}]*--v2-paper:\s*#242422;[^}]*--v2-indigo:\s*#e9e9e6;/);
    assert.ok(revisions.includes('.nfc-v2-revision-table tbody tr:focus-within'));
    assert.ok(revisions.includes('font-variant-numeric: tabular-nums'));
    assert.ok(revisions.includes('z-index: 1400 !important'));
    assert.ok(revisions.includes('z-index: 1401 !important'));
    assert.doesNotMatch(revisions, /#2875e9|#83b5ff/);
  });

  test('Plan Detail retains muted numeric ledger hierarchy and neutral light/dark fallback', () => {
    assert.match(plans, /--nfc-plan-accent:var\(--nfc-accent,#252525\);/);
    assert.match(plans, /\[data-theme='dark'\] \.nfc-plan-detail-page\s*\{[^}]*--nfc-plan-accent:var\(--nfc-accent,#e9e9e6\);/);
    assert.ok(plans.includes('font-variant-numeric:tabular-nums'));
    assert.ok(plans.includes('.nfc-v2-plan-table tbody tr:focus-within'));
    assert.ok(plans.includes('.nfc-v2-plan-table-scroll'));
    assert.ok(plans.includes('.nfc-v2-plan-notice.is-warning'));
    assert.ok(plans.includes('.nfc-v2-plan-notice.is-error'));
    assert.doesNotMatch(plans, /#286ff1|#83b5ff|#1a2434/);
  });

  test('Server-backed workflow revisions and guarded Plan transitions are preserved', () => {
    const builder = read('src/pages/Workflows/WorkflowBuilder.tsx');
    const drawer = read('src/components/workflows/RevisionDrawer.tsx');
    const detail = read('src/pages/Plans/PlanDetail.tsx');
    for (const marker of ['isDirty', 'RevisionDrawer', 'canConfirmWorkflowRollback', 'saveMutation', 'WorkflowPreviewPanel']) {
      assert.ok(builder.includes(marker), marker);
    }
    for (const marker of ['expected_current_revision: intent.expectedRevision', '<ConsoleConfirmDialog', 'definition_sha256']) {
      assert.ok(drawer.includes(marker), marker);
    }
    for (const marker of [
      'plansApi.freezePlan(planId)', 'plansApi.validatePlan(planId)', 'plansApi.executePlan(planId)',
      'canPlanLifecycleAction(', 'samePlanConfirmation(', 'planConfirmationSnapshot(',
      'plansApi.getPlanDetail(planId, page, pageSize)', '<ConsoleConfirmDialog',
    ]) assert.ok(detail.includes(marker), marker);
  });
});
