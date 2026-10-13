import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const ledger = read('src/styles/console-v2-quarantine-ledger.css');
const single = read('src/styles/console-v2-quarantine-single-actions.css');
const bulk = read('src/styles/console-v2-quarantine-bulk-dialogs.css');

describe('Pure White Stage 4B Quarantine detail and safe overlays', () => {
  test('ledger uses true neutral surfaces in light and deliberate dark mode', () => {
    for (const token of [
      '--nfc-q-ledger-paper:var(--nfc-surface-1,#ffffff)',
      '--nfc-q-ledger-soft:var(--nfc-surface-2,#f5f5f3)',
      '--nfc-q-ledger-text:var(--nfc-text,#20201f)',
      '--nfc-q-ledger-line:var(--nfc-hairline,#eaeae7)',
      '--nfc-q-ledger-accent:var(--nfc-accent,#262625)',
      "[data-theme='dark'] .nfc-v2-quarantine-ledger",
      '--nfc-q-ledger-paper:var(--nfc-surface-1,#242422)',
      '--nfc-q-ledger-accent:var(--nfc-accent,#e9e9e6)',
    ]) assert.ok(ledger.includes(token), token);
    assert.doesNotMatch(ledger, /#286ff1|#83b5ff|#172338|#1a2434|--v2-indigo/);
  });

  test('ledger table paths, keyboard focus, mobile selection and reduced motion are readable', () => {
    for (const token of [
      'overscroll-behavior-x:contain',
      'font-variant-numeric:tabular-nums',
      '.nfc-v2-quarantine-table tbody tr:focus-within',
      '.nfc-v2-quarantine-table .nfc-v2-quarantine-checkbox:focus-visible',
      '.nfc-v2-quarantine-mobile-list .nfc-quarantine-mobile-card:focus-within',
      'overflow-wrap:anywhere', 'min-height:44px',
      'prefers-reduced-motion:reduce',
    ]) assert.ok(ledger.includes(token), token);
    const source = read('src/pages/Quarantine/index.tsx');
    for (const token of [
      'getBulkSelectableEntryIds(items)',
      "record.state !== 'active'",
      "['restored', 'purged', 'abandoned', 'conflict']",
      'cleanupInFlight.current',
      '<ConsoleConfirmDialog',
    ]) assert.ok(source.includes(token), token);
  });

  test('single restore/purge Portal uses neutral tokens and distinct danger/success/warning', () => {
    for (const token of [
      '--nfc-q-text:var(--nfc-text,#20201f)',
      '--nfc-q-accent:var(--nfc-accent,#262625)',
      '--nfc-q-paper:var(--nfc-surface-1,#242422)',
      '--nfc-q-accent:var(--nfc-accent,#e9e9e6)',
      '.nfc-v2-quarantine-alert.is-danger',
      '.nfc-v2-quarantine-alert.is-warning',
      '.nfc-v2-quarantine-alert.is-success',
      'border-color:#ce4962',
      'overscroll-behavior:contain',
      'max-height:calc(100dvh - 16px)',
    ]) assert.ok(single.includes(token), token);
    assert.doesNotMatch(single, /#286ff1|#83b5ff|#1a2434|#182338/);
  });

  test('single restore choices have selection, keyboard, disabled and mobile-safe close targets', () => {
    for (const token of [
      '.nfc-v2-quarantine-options label.is-selected',
      '.nfc-v2-quarantine-options label:focus-within',
      '.nfc-v2-quarantine-options label:has(input:disabled)',
      'min-width:44px;min-height:44px',
      'overflow-wrap:anywhere',
      'prefers-reduced-motion:reduce',
    ]) assert.ok(single.includes(token), token);
    const restore = read('src/pages/Quarantine/RestoreModal.tsx');
    const purge = read('src/pages/Quarantine/PurgeConfirmModal.tsx');
    for (const token of [
      'getQuarantineRestoreAvailability(isSafeMode, payload.conflict_policy, payload.custom_target)',
      'quarantineApi.restore(entry.id, payload)',
      'value="skip"', 'value="rename"', 'value="manual"',
      'onPointerDownOutside={event => event.preventDefault()}',
    ]) assert.ok(restore.includes(token), token);
    for (const token of [
      'getQuarantinePurgeAvailability(isAdmin, allowDelete, allowMutation, confirmInput)',
      "quarantineApi.purge(entry.id, { confirmation: 'DELETE' })",
      'if (busy || inFlight.current) event.preventDefault()',
      'onPointerDownOutside={event => event.preventDefault()}',
    ]) assert.ok(purge.includes(token), token);
  });

  test('bulk Draft dialogs keep readable neutral light/dark and semantic blocked counts', () => {
    for (const token of [
      '--nfc-bulk-ink:var(--nfc-text,#20201f)',
      '--nfc-bulk-accent:var(--nfc-accent,#262625)',
      '--nfc-bulk-bg:var(--nfc-surface-1,#242422)',
      '--nfc-bulk-accent:var(--nfc-accent,#e9e9e6)',
      '.nfc-v2-quarantine-bulk-note.is-danger',
      '.nfc-v2-quarantine-bulk-note.is-warning',
      '.nfc-v2-quarantine-bulk-note.is-success',
      '.nfc-v2-quarantine-bulk-metrics > .is-blocked',
      '.nfc-v2-quarantine-bulk-metrics > .is-allowed',
      'font-variant-numeric:tabular-nums',
      'overscroll-behavior:contain',
    ]) assert.ok(bulk.includes(token), token);
    assert.doesNotMatch(bulk, /#286ff1|#83b5ff|#1a2434|#182338/);
  });

  test('bulk choices retain keyboard/disabled states and never bypass Preview-Draft authority', () => {
    for (const token of [
      '.nfc-v2-quarantine-bulk-options label.is-selected',
      '.nfc-v2-quarantine-bulk-options label:focus-within',
      '.nfc-v2-quarantine-bulk-options label:has(input:disabled)',
      'max-height:calc(100dvh - 16px)',
      'min-width:44px;min-height:44px',
      'overflow-wrap:anywhere',
      'prefers-reduced-motion:reduce',
    ]) assert.ok(bulk.includes(token), token);
    const restore = read('src/pages/Quarantine/BulkRestoreModal.tsx');
    const purge = read('src/pages/Quarantine/BulkPurgeModal.tsx');
    for (const source of [restore, purge]) {
      for (const token of [
        'expected_preview_digest',
        'preview.blocked_count',
        'onPointerDownOutside={event => event.preventDefault()}',
        'onEscapeKeyDown={event => { if (busy || inFlight.current) event.preventDefault(); }}',
      ]) assert.ok(source.includes(token), token);
      assert.doesNotMatch(source, /quarantineApi\.(restore|purge)\(/);
    }
    assert.ok(purge.includes("confirmation: 'DELETE' as const"));
    const shared = read('src/styles/console-v2-task-overlays.css');
    assert.ok(shared.includes('.nfc-v2-confirm-overlay'));
    assert.ok(shared.includes('.nfc-v2-confirm-dialog'));
    const scrim = read('src/styles/console-v2.css');
    assert.match(scrim, /\.nfc-v2-dialog-overlay\s*\{[^}]*backdrop-filter:\s*none;/);
  });
});
