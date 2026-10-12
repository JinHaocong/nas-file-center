import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { getQuarantinePurgeAvailability, getQuarantineRestoreAvailability } from
  '../src/components/quarantine/quarantine_rules';
import { quarantineApi } from '../src/api/quarantine';
import { api } from '../src/api/client';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const restore = () => read('src/pages/Quarantine/RestoreModal.tsx');
const purge = () => read('src/pages/Quarantine/PurgeConfirmModal.tsx');

describe('Console v2 Quarantine native one-item safety dialogs', () => {
  test('restore capability defaults to skip and denies unsafe/invalid manual targets', () => {
    assert.equal(getQuarantineRestoreAvailability(false, 'skip').canRestore, true);
    assert.equal(getQuarantineRestoreAvailability(false, 'rename').canRestore, true);
    assert.equal(getQuarantineRestoreAvailability(true, 'skip').canRestore, false);
    assert.equal(getQuarantineRestoreAvailability(false, 'manual', 'relative/file').canRestore, false);
    assert.equal(getQuarantineRestoreAvailability(false, 'manual', '  ').canRestore, false);
    assert.equal(getQuarantineRestoreAvailability(false, 'manual', '/data/restored/file').canRestore, true);
  });
  test('purge requires admin + mutation + delete + exact uppercase DELETE', () => {
    assert.equal(getQuarantinePurgeAvailability(true, true, true, 'DELETE').canPurge, true);
    for (const word of ['', 'Delete', 'delete', 'DELETE ', ' DELETE', 'DELETE\n']) {
      assert.equal(getQuarantinePurgeAvailability(true, true, true, word).canPurge, false, word);
    }
    assert.equal(getQuarantinePurgeAvailability(false, true, true, 'DELETE').canPurge, false);
    assert.equal(getQuarantinePurgeAvailability(true, false, true, 'DELETE').canPurge, false);
    assert.equal(getQuarantinePurgeAvailability(true, true, false, 'DELETE').canPurge, false);
  });
  test('restore sends the original API endpoint and exact manual conflict payload', async () => {
    const post = api.post;
    let path = ''; let payload: unknown;
    api.post = ((p: string, data: unknown) => {
      path = p; payload = data;
      return Promise.resolve({ state: 'restored', restored_to_path: '/data/new' });
    }) as typeof api.post;
    try {
      await quarantineApi.restore(19, { conflict_policy: 'manual', custom_target: '/data/new' });
      assert.equal(path, '/api/quarantine/19/restore');
      assert.deepEqual(payload, { conflict_policy: 'manual', custom_target: '/data/new' });
    } finally { api.post = post; }
  });
  test('purge sends exact DELETE confirmation to the existing unlink endpoint', async () => {
    const post = api.post;
    let path = ''; let payload: unknown;
    api.post = ((p: string, data: unknown) => {
      path = p; payload = data;
      return Promise.resolve({ state: 'purged', purge_semantics: 'unlink_v1' });
    }) as typeof api.post;
    try {
      await quarantineApi.purge(19, { confirmation: 'DELETE' });
      assert.equal(path, '/api/quarantine/19/purge');
      assert.deepEqual(payload, { confirmation: 'DELETE' });
    } finally { api.post = post; }
  });
  test('restore keeps exact three conflict modes and default skip after opening', () => {
    const s = restore();
    for (const token of [
      "useState<QuarantineConflictPolicy>('skip')", "setConflictPolicy('skip')",
      'getQuarantineRestoreAvailability', 'value="skip"', 'value="rename"',
      'value="manual"', "conflictPolicy === 'manual' ? customTarget.trim() : undefined",
      'conflict_policy: conflictPolicy', "isSafeMode", 'ALLOW_MUTATION=false',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /overwrite:\s*true|conflict_policy:\s*'overwrite'/);
  });
  test('restore rechecks safety before submit, awaits result and avoids double request', () => {
    const s = restore();
    for (const token of [
      'if (!entry || !open || inFlight.current || busy) return;',
      'getQuarantineRestoreAvailability(isSafeMode, conflictPolicy, customTarget)',
      'if (!checked.canRestore)', 'inFlight.current = true',
      'await restoreMutation.mutateAsync(payload)',
      'inFlight.current = false',
      "onEscapeKeyDown={event => { if (busy || inFlight.current) event.preventDefault(); }}",
      'onPointerDownOutside={event => event.preventDefault()}',
    ]) assert.ok(s.includes(token), token);
  });
  test('restore reports skipped paths and conflict_resolved without inventing success', () => {
    const s = restore();
    for (const token of [
      "res.state === 'skipped'", 'toast.info(res.reason',
      'res.conflict_resolved', 'res.restored_to_path',
      "queryKey: ['quarantineList']", "queryKey: ['dashboardSummary']",
      'onSuccess();', 'onClose();',
    ]) assert.ok(s.includes(token), token);
  });
  test('purge checks host switches and exact DELETE at both UI and request layer', () => {
    const s = purge();
    for (const token of [
      'getQuarantinePurgeAvailability(', 'isAdmin, allowDelete, allowMutation, confirmInput',
      "confirmation: 'DELETE'", "confirmInput !== 'DELETE'", 'ALLOW_MUTATION=false',
      'ALLOW_DELETE=false', 'disabled={!availability.canPurge || busy}',
      'inFlight.current', 'await purgeMutation.mutateAsync()',
    ]) assert.ok(s.includes(token), token);
  });
  test('purge keeps advisory survivor and independent-copy scopes separate', () => {
    const s = purge();
    for (const token of [
      'purge_semantics', 'removed_count', 'survivor_scope', 'survivor_status',
      'hardlink_survivor_paths', 'independent_copy_paths', 'indexed_roots_only',
      "purgeResult.survivor_status === 'found'",
      "purgeResult.survivor_status === 'incomplete'",
      '同内容但不同 inode 的独立副本', 'advisory 查询不完整',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /物理擦除|彻底从磁盘|磁盘字节已完全擦除/);
  });
  test('purge result stays readable until explicitly closed after server success', () => {
    const s = purge();
    for (const token of [
      'setPurgeResult(result)', 'onSuccess();',
      'purgeResult ? (', 'onClick={closeSafely}>关闭',
      'if (!entry || !open || busy || inFlight.current || purgeResult) return;',
      'void queryClient.invalidateQueries',
    ]) assert.ok(s.includes(token), token);
  });
  test('native dialogs have Radix portal/title/description and controlled safe closing', () => {
    for (const s of [purge(), restore()]) {
      for (const token of [
        "@radix-ui/react-dialog", '<Dialog.Root', '<Dialog.Portal>',
        '<Dialog.Overlay', '<Dialog.Content', '<Dialog.Title', '<Dialog.Description',
        'closeSafely', 'if (!busy && !inFlight.current)', 'onPointerDownOutside',
      ]) {
        // restore reverses the two predicates but retains the same lock.
        if (token === 'if (!busy && !inFlight.current)' && s.includes('if (!inFlight.current && !busy)')) continue;
        assert.ok(s.includes(token), token);
      }
      assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Modal\b|<Form\b|<Radio\.Group\b/);
    }
  });
  test('warning and successful results remain scoped to one quarantine entry', () => {
    for (const s of [purge(), restore()]) {
      assert.ok(s.includes('if (!entry) return null'));
      assert.ok(s.includes('entry.id'));
      assert.ok(s.includes('queryClient.invalidateQueries'));
    }
    assert.ok(purge().includes('只删除 NFC 拥有并经过身份核验的隔离区路径'));
    assert.ok(purge().includes('不会扩大到同 inode 的外部 hard link'));
  });
  test('quarantine page still binds both single-entry modals to existing props', () => {
    const s = read('src/pages/Quarantine/index.tsx');
    for (const token of [
      '<RestoreModal entry={restoreEntry}', 'isSafeMode={isSafeMode}',
      '<PurgeConfirmModal entry={purgeEntry}',
      'isAdmin={Boolean(isAdmin)}', 'allowMutation={!isSafeMode}',
      'allowDelete={allowDelete}',
    ]) assert.ok(s.includes(token), token);
  });
  test('portal styles cover mobile, dark, semantic warnings, focus and reduced-motion', () => {
    const s = read('src/styles/console-v2-quarantine-single-actions.css');
    for (const token of [
      '.nfc-v2-quarantine-dialog', '.nfc-v2-quarantine-alert',
      '.nfc-v2-quarantine-facts', '.nfc-v2-quarantine-options',
      '.nfc-v2-quarantine-token', '.nfc-v2-quarantine-results',
      "[data-theme='dark']", 'focus-visible', 'max-width:767px',
      'prefers-reduced-motion:reduce', 'min-height:44px',
    ]) assert.ok(s.includes(token), token);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-quarantine-single-actions.css';"));
  });
});
