import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');
const step = read('src/styles/console-v2-workflow-step-card.css');
const fields = read('src/styles/console-v2-workflow-fields.css');
const org = read('src/styles/console-v2-organizer-profile-form.css');
const dedupe = read('src/styles/console-v2-dedupe-overlays.css');
const safe = read('src/styles/console-v2-dedupe-safety.css');
const scorer = read('src/styles/console-v2-dedupe-scorer.css');

describe('Pure White Stage 3B complex form details', () => {
  test('StepCard uses neutral chips and safe long summaries without breaking disclosure', () => {
    for (const token of [
      '--nfc-info-soft: var(--nfc-accent-soft)',
      'nfc-v2-step-card:focus-within', 'overflow-wrap: anywhere',
      'nfc-v2-step-type.is-dedupe', 'min-height: 44px',
    ]) assert.ok(step.includes(token), token);
    assert.doesNotMatch(step, /#8668d4|#e2ae52/);
    const source = read('src/components/workflows/StepCard.tsx');
    for (const token of [
      'aria-expanded={expanded}', 'hidden={!expanded}', 'readOnly',
      'handleMoveUp', 'handleMoveDown', 'handleDelete',
    ]) assert.ok(source.includes(token), token);
  });

  test('Workflow root cards support keyboard-visible neutral checked/hover states', () => {
    for (const token of [
      ':has(input:checked) { background: var(--nfc-accent-soft)',
      '.nfc-v2-step-root-option:focus-within',
      '.nfc-v2-step-root-option:hover:not(:has(input:disabled))',
      'accent-color: var(--nfc-accent)',
      'min-height: 44px',
    ]) assert.ok(fields.includes(token), token);
  });

  test('Organizer Portal is neutral across themes while DirectoryPicker remains on top', () => {
    for (const token of [
      '--nfc-accent: #252525', '--nfc-accent: #e9e9e6',
      '--nfc-text: #20201f', '--nfc-surface-1: #242422',
      'z-index: 1140', 'z-index: 1141', 'overflow-wrap: anywhere',
      'max-height: calc(100dvh - 12px)', ':focus-visible',
    ]) assert.ok(org.includes(token), token);
    assert.doesNotMatch(org, /#2875e9|#83b5ff|#1a2434|#203452/);
    assert.ok(read('src/styles/console-v2-directory-modal.css').includes('z-index: 1201'));
    const source = read('src/pages/Organizer/ProfileFormModal.tsx');
    for (const token of [
      'onPointerDownOutside', 'onEscapeKeyDown',
      'canSubmitOrganizerProfileForm',
      'validateWorkflowOrganizerSnapshot(draft)', 'savingRef.current',
    ]) assert.ok(source.includes(token), token);
  });

  test('Dedupe Portal uses charcoal primary with dark contrast and mobile touch controls', () => {
    for (const token of [
      '--nfc-dedupe-accent: #252525', '--nfc-dedupe-accent: #e9e9e6',
      '--nfc-dedupe-primary-text: #ffffff', '--nfc-dedupe-primary-text: #20201f',
      'color: var(--nfc-dedupe-primary-text)',
      'z-index: 1220', 'z-index: 1221', 'min-height: 44px',
      'overflow-wrap: anywhere', ':focus-visible',
      'is-error', 'is-success', 'is-warning', '#258868',
    ]) assert.ok(dedupe.includes(token), token);
    assert.doesNotMatch(dedupe, /#2878ef|#83b5ff|#1a2434/);
    const source = read('src/pages/Scans/DedupePlanModal.tsx');
    for (const token of [
      'validateClassicDedupe(values)', 'scansApi.createDedupePlan',
      'onEscapeKeyDown', 'onPointerDownOutside',
    ]) assert.ok(source.includes(token), token);
  });

  test('Scorer maintains numeric truth, validation and visible focus in both themes', () => {
    for (const token of [
      '--nfc-scorer-accent: #252525', '--nfc-scorer-accent: #e9e9e6',
      '.nfc-v2-scorer-rule-row:focus-within',
      '.nfc-v2-scorer-option:focus-within',
      'font-variant-numeric: tabular-nums', 'min-height: 44px',
      'nfc-v2-scorer-validation', 'nfc-v2-scorer-notice',
    ]) assert.ok(scorer.includes(token), token);
    assert.doesNotMatch(scorer, /#2878ef|#83b5ff|#1a2434/);
    assert.ok(read('src/components/dedupe/DedupeScorerConfigEditor.tsx').includes('disabled'));
  });

  test('Storage safety keeps disabled guards and meaningful red/amber/green statuses', () => {
    for (const token of [
      '--nfc-safe-accent: #252525', '--nfc-safe-accent: #e9e9e6',
      'nfc-v2-storage-action-option:has(input:disabled)',
      'nfc-v2-storage-action-note.is-warning',
      'nfc-v2-storage-action-note.is-error',
      'nfc-v2-capability-badge.is-supported',
      'nfc-v2-capability-badge.is-unsupported',
      'nfc-v2-capability-badge.is-unknown', 'min-height: 44px',
    ]) assert.ok(safe.includes(token), token);
    assert.doesNotMatch(safe, /#2878ef|#83b5ff|#1a2434/);
    const source = read('src/components/dedupe/DedupeStorageActionPanel.tsx');
    for (const token of [
      'canSelectStorageAction', 'canRunCapabilityProbe',
      'onProbeCapabilities', 'disabled',
    ]) assert.ok(source.includes(token), token);
  });
});
