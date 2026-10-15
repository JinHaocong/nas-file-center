import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const css = read('src/styles/console-v2-quarantine-bulk-dialogs.css');
const browser = read('scripts/browser-quarantine-bulk-overlays.mjs');
const purge = read('src/pages/Quarantine/BulkPurgeModal.tsx');
const restore = read('src/pages/Quarantine/BulkRestoreModal.tsx');

describe('Pure White Stage 5E-AE screenshot-led Quarantine Purge footer reachability', () => {
  test('Purge-only scrolling keeps header/actions fixed and aligns dense content to title', () => {
    for (const token of [
      '.nfc-quarantine-bulk-purge-modal.nfc-v2-quarantine-bulk-dialog',
      'display:flex;flex-direction:column;overflow:hidden;',
      '.nfc-quarantine-bulk-purge-modal > .nfc-v2-dialog-heading',
      '.nfc-quarantine-bulk-purge-modal > .nfc-v2-confirm-actions',
      '.nfc-quarantine-bulk-purge-modal > .nfc-v2-quarantine-bulk-body',
      'flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior:contain;',
      'padding:15px 24px 19px;',
      'padding:14px 18px 16px;',
      'border-top:1px solid var(--nfc-bulk-line);',
    ]) assert.ok(css.includes(token), token);
    assert.ok(purge.includes('nfc-quarantine-bulk-purge-modal'));
    assert.ok(purge.includes('className="nfc-v2-quarantine-bulk-metrics" role="status" aria-live="polite"'));
    assert.ok(!purge.includes("toast.success('Preview 完成：'"));
    assert.ok(restore.includes('nfc-quarantine-bulk-restore-modal'));
    assert.ok(!css.includes('.nfc-quarantine-bulk-restore-modal > .nfc-v2-quarantine-bulk-body'));
  });

  test('32 actual Chromium cases assert danger footer, interior scroll, DELETE visibility and safe state', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      'async function assertPurgeFooterAndScroll(page, width, state)',
      'footerBox.bottom <= Math.min(modalBox.bottom, innerHeight) + 2',
      'buttonBox.bottom <= Math.min(footerBox.bottom, innerHeight) + 2',
      'insetBox.left >= modalBox.left + gutter',
      'body.scrollHeight > body.clientHeight + 15',
      "state === 'bottom'",
      "token?.value === 'DELETE'",
      "hit === token, 'A floating toast masks the visible DELETE input'",
      '.nfc-v2-quarantine-bulk-metrics[role="status"]',
      "await assertPurgeFooterAndScroll(page, width, 'ready');",
      "await assertPurgeFooterAndScroll(page, width, 'bottom');",
      "'purge-review-bottom-' + label",
      "assert.equal(await generatePurge.isEnabled(), true,",
      "request.method() === 'POST' && url.pathname === '/api/quarantine/bulk-preview'",
      "status: 405",
      "assert.deepEqual(forbidden, []",
      "assert.deepEqual(external, []",
      '32/32 viewport/theme cases; 160 screenshots;',
    ]) assert.ok(browser.includes(token), token);
    assert.ok(read('../.github/workflows/ui-v044-validation.yml')
      .includes('node scripts/browser-quarantine-bulk-overlays.mjs'));
  });

  test('visual layout changes never change exact DELETE, RBAC, digest or Draft-only semantics', () => {
    for (const token of [
      "const isConfirmed = confirmInput === 'DELETE'",
      'isConfirmed &&',
      'getQuarantinePurgeAvailability(isAdmin, allowDelete, allowMutation)',
      'preview.blocked_count === 0',
      'expected_preview_digest: preview.preview_digest',
      "confirmation: 'DELETE' as const",
      "action: 'purge' as const",
      "await quarantineApi.bulkPlan(snapshot)",
      'inFlight.current',
      'Freeze → Validate → Execute',
    ]) assert.ok(purge.includes(token), token);
    assert.doesNotMatch(browser, /quarantineApi\.(bulkPlan|purge|restore)\(/);
  });
});
