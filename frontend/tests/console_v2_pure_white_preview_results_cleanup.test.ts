import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string): string => readFileSync(resolve(process.cwd(), path), 'utf8');
const organizer = read('src/styles/console-v2-organizer-preview.css');
const advanced = read('src/styles/console-v2-advanced-dedupe.css');
const explain = read('src/styles/console-v2-dedupe-explain.css');
const cleanup = read('src/styles/console-v2-plan-cleanup-controls.css');

describe('Pure White Stage 3C: preview, explanation and destructive-history affordances', () => {
  test('Organizer Preview uses neutral light/dark surfaces, a readable ledger and keyboard focus', () => {
    for (const token of [
      '--nfc-opv-text:#20201f', '--nfc-opv-accent:#252525',
      '--nfc-opv-paper:#242422', '--nfc-opv-accent:#e9e9e6',
      '.nfc-v2-organizer-filter label:focus-within',
      '.nfc-v2-organizer-proposal-table tbody tr:focus-within',
      'font-variant-numeric:tabular-nums',
      '.nfc-v2-organizer-target-path .nfc-code-path',
      '.nfc-organizer-proposal-mobile-card:focus-within',
      'min-height:44px', 'prefers-reduced-motion:reduce',
    ]) assert.ok(organizer.includes(token), token);
    assert.doesNotMatch(organizer, /#2878ef|#83b5ff|#1a2434/);
    for (const status of ['is-warning', 'is-success', 'is-danger']) {
      assert.ok(organizer.includes('.nfc-v2-organizer-stage-notice.' + status), status);
    }
  });

  test('Advanced Dedupe result list maintains original status meaning and neutral table focus', () => {
    for (const token of [
      'nfc-v2-dedupe-filter-search:focus-within',
      '.nfc-v2-dedupe-table tbody tr:focus-within',
      'font-variant-numeric:tabular-nums',
      'overflow-wrap: anywhere', 'overscroll-behavior-x: contain',
      '.nfc-v2-dedupe-eligibility.is-eligible',
      '.nfc-v2-dedupe-eligibility.is-safety_excluded',
      '@media (max-width: 767px)',
    ]) assert.ok(advanced.includes(token), token);
    assert.match(advanced, /\.nfc-v2-dedupe-preview :is\(input,select,button\):focus-visible \{ outline: 2px solid var\(--nfc-accent\)/);
    assert.doesNotMatch(advanced, /#2878ef|#83b5ff|#1a2434|rgba\(70,123,190/);
  });

  test('Dedupe generation authority dialog has legible charcoal/light and dark-button contrast', () => {
    for (const token of [
      '--nfc-adv-dialog-accent: #252525',
      '--nfc-adv-dialog-primary-text: #ffffff',
      '--nfc-adv-dialog-accent: #e9e9e6',
      '--nfc-adv-dialog-primary-text: #20201f',
      'color: var(--nfc-adv-dialog-primary-text)',
      '.nfc-v2-advanced-dedupe-overlay { z-index: 1280; }',
      'position: fixed; z-index: 1281',
      'max-height:calc(100dvh - 16px)',
      'min-height:44px',
    ]) assert.ok(advanced.includes(token), token);
    assert.ok(advanced.includes('is-warning { border-color: #cf9b50'));
    assert.ok(advanced.includes('.nfc-v2-advanced-dedupe-dialog :is(button):focus-visible'));
    const dialog = read('src/components/dedupe/DedupeActionDialog.tsx');
    for (const token of ['onEscapeKeyDown', 'onPointerDownOutside', 'if (busy) event.preventDefault()', 'Freeze -&gt; Validate -&gt; Execute']) {
      assert.ok(dialog.includes(token), token);
    }
  });

  test('Dedupe explain remains read-only and independently themed inside its layered Radix sheet', () => {
    for (const token of [
      '--nfc-exp-accent: #252525', '--nfc-exp-accent: #e9e9e6',
      '--v2-indigo: #252525', '--v2-indigo: #e9e9e6',
      'z-index: 1225', 'z-index: 1226',
      '.nfc-v2-dedupe-explain-table tbody tr:focus-within',
      'overflow-wrap: anywhere', '.is-numeric',
      '[data-theme=', 'prefers-reduced-motion: reduce',
    ]) assert.ok(explain.includes(token), token);
    for (const status of ['is-success', 'is-warning', 'is-error']) {
      assert.ok(explain.includes('.nfc-v2-dedupe-decision-tag.' + status), status);
    }
    assert.doesNotMatch(explain, /#2878ef|#83b5ff|#1a2434/);
    const drawer = read('src/components/dedupe/DedupeExplainDrawer.tsx');
    for (const token of [
      'member.incomplete', '后端 canonical 分析数据', 'findDuplicateGroupSiblings',
      'navigator.clipboard.writeText', '前端不进行任何打分计算',
    ]) assert.ok(drawer.includes(token), token);
  });

  test('Plan history offers neutral selected and focus states without weakening disable/scroll guards', () => {
    for (const token of [
      '.nfc-v2-plan-history-options label:has(input:checked)',
      'background:var(--nfc-accent-soft)',
      '.nfc-v2-plan-history-options label:focus-within',
      '.nfc-v2-plan-history-options label:has(input:disabled)',
      'cursor:not-allowed;opacity:.6',
      'overscroll-behavior:contain', 'min-height:44px',
      'prefers-reduced-motion:reduce',
    ]) assert.ok(cleanup.includes(token), token);
    const history = read('src/components/plans/PlanHistoryCleanupModal.tsx');
    for (const token of [
      "value: 'completed'", "value: 'failed'",
      'plansApi.clearHistory(statuses)',
      'if (submitting.current || selectedStatuses.length === 0) return',
      'selectedStatuses.length === 0',
      'onPointerDownOutside={event => event.preventDefault()}',
      'onEscapeKeyDown',
    ]) assert.ok(history.includes(token), token);
  });

  test('Read-only preview snapshots and digest-bound Plan creation remain server authoritative', () => {
    const preview = read('src/pages/Organizer/ProfilePreview.tsx');
    for (const token of [
      'organizerProfilesApi.previewProfile(profile.id',
      'organizerProfilesApi.createPlan(profile.id',
      'expected_preview_digest: params.expectedPreviewDigest',
      'setPreviewDigest(undefined)', 'if (requestId !== sequenceRef.current) return',
    ]) assert.ok(preview.includes(token), token);
    const dedupe = read('src/pages/Scans/AdvancedDedupePage.tsx');
    for (const token of [
      'scansApi.dedupePreview(scanId',
      'scansApi.createAdvancedDedupePlan(scanId',
      'expected_preview_digest: dedupeState.acceptedPreviewDigest',
      '!canGeneratePlan(dedupeState)',
      'generateInFlight.current',
    ]) assert.ok(dedupe.includes(token), token);
    assert.doesNotMatch(preview + dedupe, /deleteFiles\(|executePlan\(/);
  });
});
