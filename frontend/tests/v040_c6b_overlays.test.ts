import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.0 C6B overlay consistency contract', () => {
  test('all named drawers opt into the shared responsive drawer chrome', () => {
    for (const path of [
      'src/components/dedupe/DedupeExplainDrawer.tsx',
      'src/components/plans/StaleRebuildDrawer.tsx',
      'src/components/tasks/TaskDetailDrawer.tsx',
      'src/components/workflows/RevisionDrawer.tsx',
      'src/pages/Plans/OperationJournalDrawer.tsx',
    ]) {
      const source = read(path);
      assert.match(source, /nfc-overlay-drawer/, path);
    }
  });

  test('all named modals opt into the shared responsive modal chrome', () => {
    for (const path of [
      'src/components/ChangePasswordModal.tsx',
      'src/components/DirectoryPicker/DirectoryPickerModal.tsx',
      'src/components/plans/PlanHistoryCleanupModal.tsx',
      'src/components/tasks/TaskHistoryCleanupModal.tsx',
      'src/pages/Organizer/ProfileFormModal.tsx',
      'src/pages/Quarantine/BulkPurgeModal.tsx',
      'src/pages/Quarantine/BulkRestoreModal.tsx',
      'src/pages/Quarantine/PurgeConfirmModal.tsx',
      'src/pages/Quarantine/RestoreModal.tsx',
      'src/pages/Scans/DedupePlanModal.tsx',
    ]) {
      const source = read(path);
      assert.match(source, /nfc-overlay-modal/, path);
    }
  });

  test('RevisionDrawer styles both drawer and definition-inspection modal', () => {
    const source = read('src/components/workflows/RevisionDrawer.tsx');
    assert.match(source, /nfc-overlay-drawer/);
    assert.match(source, /nfc-overlay-modal/);
    assert.match(source, /expected_current_revision/);
    assert.match(source, /canRollbackWorkflow/);
  });

  test('critical quarantine overlays preserve irreversible safety authority', () => {
    const purge = read('src/pages/Quarantine/BulkPurgeModal.tsx');
    for (const semantic of ['ALLOW_DELETE=false', 'expected_preview_digest', "confirmation: 'DELETE'", "confirmInput === 'DELETE'", 'blocked_count === 0']) {
      assert.ok(purge.includes(semantic), `BulkPurge missing ${semantic}`);
    }

    const restore = read('src/pages/Quarantine/BulkRestoreModal.tsx');
    for (const semantic of ['expected_preview_digest', 'blocked_count === 0', 'conflict_strategy']) {
      assert.ok(restore.includes(semantic), `BulkRestore missing ${semantic}`);
    }
  });

  test('task and plan overlays retain operational actions and journal authority', () => {
    const task = read('src/components/tasks/TaskDetailDrawer.tsx');
    for (const semantic of ['cancel', 'pause', 'resume']) {
      assert.match(task, new RegExp(semantic, 'i'));
    }

    const journal = read('src/pages/Plans/OperationJournalDrawer.tsx');
    assert.match(journal, /planId/);
    assert.match(journal, /operation/i);
  });

  test('shared overlay CSS defines restrained chrome and mobile behavior', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-overlay-modal',
      '.nfc-overlay-drawer',
      '.nfc-overlay-modal .ant-modal-content',
      '.nfc-overlay-drawer .ant-drawer-content',
      '.nfc-overlay-drawer .ant-drawer-content-wrapper',
    ]) {
      assert.match(css, new RegExp(selector.replaceAll('.', '\\.')));
    }
  });
});
