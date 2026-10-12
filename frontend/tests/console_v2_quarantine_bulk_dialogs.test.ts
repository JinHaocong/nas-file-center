import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  getBulkRestoreAvailability, getQuarantinePurgeAvailability,
  isBulkPreviewSelectionCurrent,
} from '../src/components/quarantine/quarantine_rules';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const restore = () => read('src/pages/Quarantine/BulkRestoreModal.tsx');
const purge = () => read('src/pages/Quarantine/BulkPurgeModal.tsx');

describe('Console v2 native Quarantine bulk Preview → Draft gates', () => {
  test('restore policy admits skip/rename but blocks read-only and unknown modes', () => {
    assert.equal(getBulkRestoreAvailability(false, 'skip').canRestore, true);
    assert.equal(getBulkRestoreAvailability(false, 'rename').canRestore, true);
    assert.equal(getBulkRestoreAvailability(true, 'skip').canRestore, false);
    assert.equal(getBulkRestoreAvailability(false, 'manual' as never).canRestore, false);
  });

  test('preview identity uses exact selected IDs, not set inclusion', () => {
    assert.equal(isBulkPreviewSelectionCurrent([5, 3, 8], [8, 5, 3]), true);
    assert.equal(isBulkPreviewSelectionCurrent([5, 3, 8], [5, 3]), false);
    assert.equal(isBulkPreviewSelectionCurrent([5, 3], [5, 3, 7]), false);
    assert.equal(isBulkPreviewSelectionCurrent([5, 5], [5, 7]), false);
  });

  test('purge capability requires administrator and both host safety switches', () => {
    assert.equal(getQuarantinePurgeAvailability(true, true, true, 'DELETE').canPurge, true);
    for (const token of ['', 'Delete', 'delete', 'DELETE ', ' DELETE', 'DELETE\n']) {
      assert.equal(getQuarantinePurgeAvailability(true, true, true, token).canPurge, false);
    }
    assert.equal(getQuarantinePurgeAvailability(false, true, true, 'DELETE').canPurge, false);
    assert.equal(getQuarantinePurgeAvailability(true, false, true, 'DELETE').canPurge, false);
    assert.equal(getQuarantinePurgeAvailability(true, true, false, 'DELETE').canPurge, false);
  });

  test('both UI entry points are Radix-controlled and remove Ant Design APIs', () => {
    for (const src of [restore(), purge()]) {
      for (const token of [
        "@radix-ui/react-dialog", '<Dialog.Root', '<Dialog.Portal',
        '<Dialog.Overlay', '<Dialog.Content', '<Dialog.Title',
        '<Dialog.Description', '<ConsoleButton', 'useConsoleToast()',
      ]) assert.ok(src.includes(token), token);
      assert.doesNotMatch(src, /from ['"]antd['"]|@ant-design\/icons|<Modal\b|<Radio\.Group\b|message\.(warning|success|error)/);
    }
  });

  test('both dialogs lock closure while Preview or Draft is in progress', () => {
    for (const src of [restore(), purge()]) {
      for (const token of [
        'const busy = previewLoading || planLoading',
        'const inFlight = useRef(false)',
        'if (!busy && !inFlight.current) onClose()',
        "onEscapeKeyDown={event => { if (busy || inFlight.current) event.preventDefault(); }}",
        'onPointerDownOutside={event => event.preventDefault()}',
      ]) assert.ok(src.includes(token), token);
    }
  });

  test('selection change invalidates previews and resets default state', () => {
    const a = restore(), b = purge();
    for (const src of [a, b]) {
      for (const token of [
        "const selectionKey = useMemo(", 'requestEpoch.current += 1',
        '}, [open, selectionKey])', 'setPreview(null)',
        'const requestKey = selectionKey', 'live.current.selectionKey === requestKey',
      ]) assert.ok(src.includes(token), token);
    }
    assert.ok(a.includes("setPolicy('skip')"));
    assert.ok(b.includes("setConfirmInput('')"));
  });

  test('stale Preview results are rejected after prop changes, not installed in UI', () => {
    const a = restore(), b = purge();
    for (const src of [a, b]) {
      for (const token of [
        'const ticket = ++requestEpoch.current',
        'requestEpoch.current === ticket',
        'if (!isCurrent()) return',
        'if (!open || busy || inFlight.current) return',
        'inFlight.current = true', 'inFlight.current = false',
      ]) assert.ok(src.includes(token), token);
    }
    assert.ok(a.includes('live.current.policy === requestPolicy'));
    assert.ok(b.includes('live.current.isAdmin && live.current.allowMutation && live.current.allowDelete'));
  });

  test('restore Preview keeps skip/rename policy and exact selected IDs', () => {
    const src = restore();
    for (const token of [
      "action: 'restore', entry_ids: ids, conflict_policy: requestPolicy",
      'result.items.some(item => item.conflict_policy !== undefined',
      'isBulkPreviewSelectionCurrent(result.entry_ids, ids)',
      'preview.items.every(item => item.conflict_policy === undefined || item.conflict_policy === policy)',
      'getBulkRestoreAvailability(isSafeMode, policy)',
      "handlePolicyChange('skip')", "handlePolicyChange('rename')",
    ]) assert.ok(src.includes(token), token);
    assert.doesNotMatch(src, /value="manual"/);
  });

  test('restore Draft remains digest-bound, fail-closed and never executes files', () => {
    const src = restore();
    for (const token of [
      'preview.blocked_count === 0', 'if (preview.blocked_count > 0)',
      'availability.canRestore', "action: 'restore' as const",
      'entry_ids: [...preview.entry_ids]', 'conflict_policy: policy',
      'expected_preview_digest: preview.preview_digest',
      'await quarantineApi.bulkPlan(snapshot)',
      'onPlanCreated(plan)', 'Freeze → Validate → Execute',
      '尚未执行任何文件变更',
    ]) assert.ok(src.includes(token), token);
    assert.doesNotMatch(src, /quarantineApi\.(restore|purge)\(/);
  });

  test('purge Preview is authorized and validates returned identity plus digest', () => {
    const src = purge();
    for (const token of [
      'getQuarantinePurgeAvailability(isAdmin, allowDelete, allowMutation)',
      "action: 'purge', entry_ids: ids", "result.action !== 'purge'",
      'isBulkPreviewSelectionCurrent(result.entry_ids, ids)',
      '!result.preview_digest', 'preview.blocked_count === 0',
      'canPurge &&', 'ALLOW_MUTATION=false', 'ALLOW_DELETE=false',
    ]) assert.ok(src.includes(token), token);
  });

  test('purge Draft requires exact DELETE and preserves frozen digest authority', () => {
    const src = purge();
    for (const token of [
      "const isConfirmed = confirmInput === 'DELETE'",
      'isConfirmed &&', 'if (preview.blocked_count > 0)',
      'getQuarantinePurgeAvailability(', 'isAdmin, allowDelete, allowMutation, confirmInput',
      "confirmation: 'DELETE' as const", "action: 'purge' as const",
      'entry_ids: [...preview.entry_ids]',
      'expected_preview_digest: preview.preview_digest',
      'await quarantineApi.bulkPlan(snapshot)',
      'onPlanCreated(plan)', '尚未删除任何文件',
    ]) assert.ok(src.includes(token), token);
    assert.doesNotMatch(src, /quarantineApi\.(restore|purge)\(/);
  });

  test('purge source retains explicit canGenerate without advisory as mutation authority', () => {
    const src = purge();
    const match = src.match(/const canGenerate = Boolean\([\s\S]*?\n  \);/);
    assert.ok(match);
    assert.match(match[0], /preview\.blocked_count === 0/);
    assert.match(match[0], /isConfirmed/);
    assert.doesNotMatch(match[0], /survivor_status|hardlink_survivor|independent_copy/);
  });

  test('blocked entries are exposed; even one blocks entire Draft', () => {
    for (const src of [restore(), purge()]) {
      for (const token of [
        "preview.items.filter(item => !item.eligible)",
        'preview.blocked_count > 0',
        'blocked 条目', 'setPreview(null)',
      ]) assert.ok(src.includes(token), token);
    }
    assert.ok(purge().includes('item.mutation_blockers?.length'));
  });

  test('purge advisory separates hard links, independent inodes and incomplete checks', () => {
    const src = purge();
    for (const token of [
      "item.purge_semantics === 'unlink_v1'",
      "item.survivor_status === 'found'",
      "item.survivor_status === 'incomplete'",
      'hardlink_survivor_paths', 'independent_copy_paths',
      'advisory_diagnostics', 'survivor_scope',
      '索引范围内', '同内容但不同 inode 的独立副本',
      '不承诺安全擦除', '不会扩大或改变删除权限',
    ]) assert.ok(src.includes(token), token);
    assert.doesNotMatch(src, /彻底从磁盘|物理清除|彻底物理销毁|磁盘字节已完全擦除/);
  });

  test('failed Draft requires fresh Preview; purge also resets typed DELETE', () => {
    const a = restore(), b = purge();
    for (const src of [a, b]) {
      assert.ok(src.includes("if (requestEpoch.current === ticket)"));
      assert.ok(src.includes('setPreview(null)'));
      assert.ok(src.includes('请重新 Preview'));
    }
    assert.ok(b.includes("setConfirmInput('')"));
    assert.ok(b.includes('重新确认'));
  });

  test('both portal dialog styles include dark, mobile, keyboard focus, reduced motion', () => {
    const css = read('src/styles/console-v2-quarantine-bulk-dialogs.css');
    for (const token of [
      '.nfc-v2-quarantine-bulk-dialog', '.nfc-v2-quarantine-bulk-options',
      '.nfc-v2-quarantine-bulk-metrics', '.nfc-v2-quarantine-bulk-card',
      '.nfc-v2-quarantine-bulk-token', "[data-theme='dark']",
      'focus-visible', 'max-width:767px', 'prefers-reduced-motion:reduce',
      'min-height:44px',
    ]) assert.ok(css.includes(token), token);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-quarantine-bulk-dialogs.css';"));
  });

  test('page integration preserves current bulk props and safe Plan navigation', () => {
    const page = read('src/pages/Quarantine/index.tsx');
    for (const token of [
      '<BulkRestoreModal', '<BulkPurgeModal',
      'entryIds={bulkRestoreEntryIds}', 'entryIds={bulkPurgeEntryIds}',
      'isSafeMode={isSafeMode}', 'isAdmin={Boolean(isAdmin)}',
      'allowMutation={!isSafeMode}', 'allowDelete={allowDelete}',
      'onPlanCreated={(plan)=>', 'navigate(', 'clearBulkSelection()',
    ]) assert.ok(page.includes(token), token);
  });
});
