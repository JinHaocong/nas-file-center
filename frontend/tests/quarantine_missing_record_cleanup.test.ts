import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { api } from '../src/api/client';
import { quarantineApi } from '../src/api/quarantine';
import { canOfferMissingPurgingRecordConfirmation, isFrozenMissingRecordConflict } from '../src/pages/Quarantine/missingCleanupPreflight';
import type { QuarantineRecoveryDiagnostic } from '../src/types';

const read = (file: string) => readFileSync(resolve(process.cwd(), file), 'utf8');

describe('externally missing quarantine payload metadata-only cleanup', () => {
  test('incident-only override explicitly targets #1106/#884 and never invokes NAS deletion', () => {
    const page = read('src/pages/Quarantine/index.tsx');
    const client = read('src/api/quarantine.ts');
    assert.match(page, /recoveryDiagnostic\.id === 1106 \|\| recoveryDiagnostic\.id === 884/);
    assert.match(page, /quarantineApi\.forgetOwnerDeletedRecord\(id\)/);
    assert.match(page, /我确认文件已删除，仅删除此数据库记录/);
    assert.match(client, /owner-deleted-record\?confirmation=FORGET_OWNER_DELETED_/);
    assert.match(page, /result\.transaction_finalized !== false/);
  });

  test('routes orphaned transaction retirement through a separate per-id confirmation', async () => {
    const original = api.delete;
    let path = '';
    api.delete = ((endpoint: string) => {
      path = endpoint;
      return Promise.resolve({
        status: 'ok', deleted: true, id: 1106, metadata_only: true,
        transaction_finalized: false,
      });
    }) as typeof api.delete;
    try {
      const result = await quarantineApi.retireOrphanTransactionRecord(1106);
      assert.equal(path,
        '/api/quarantine/1106/orphan-transaction-record?confirmation=RETIRE_ORPHAN_TX_1106');
      assert.equal(result.metadata_only, true);
      assert.equal(result.transaction_finalized, false);
    } finally {
      api.delete = original;
    }
  });

  test('orphan retirement is visible only within verified admin recovery diagnosis', () => {
    const source = read('src/pages/Quarantine/index.tsx');
    assert.match(source, /recoveryDiagnostic\.transaction_mode === 'cross_storage_transactional'/);
    assert.match(source, /recoveryDiagnostic\.transaction_evidence_observation === 'absent'/);
    assert.match(source, /recoveryDiagnostic\.payload_path_observation !== 'present'/);
    assert.match(source, /recoveryDiagnostic\.work_job_id === null/);
    assert.match(source, /recoveryDiagnostic\.plan_id === null/);
    assert.match(source, /已手动删除文件：清理孤儿事务记录/);
    assert.match(source, /setOrphanRetireTarget\(recoveryDiagnostic\.id\)/);
    assert.match(source, /retireOrphanTransactionRecord\(entryId\)/);
    assert.match(source, /result\.transaction_finalized !== false/);
    assert.match(source, /永久移除孤儿事务记录/);
    assert.match(source, /我已手动删除文件，确认仅清除记录/);
    assert.match(source, /onConfirm=\{\(\) => \{ void confirmOrphanTransactionRetirement\(\); \}\}/);
    assert.match(source, /不恢复文件，不删除任何文件/);
    assert.match(source, /安全校验拒绝清理/);
  });

  test('uses a separate, exact-confirmation endpoint instead of permanent purge', async () => {
    const original = api.delete;
    let path = '';
    api.delete = ((endpoint: string) => {
      path = endpoint;
      return Promise.resolve({ status: 'ok', deleted: true, id: 1106, metadata_only: true });
    }) as typeof api.delete;
    try {
      const result = await quarantineApi.cleanupMissingRecord(1106);
      assert.equal(path, '/api/quarantine/1106/missing-record?confirmation=CLEANUP_MISSING_RECORD');
      assert.equal(result.metadata_only, true);
    } finally {
      api.delete = original;
    }
  });

  test('requires an admin and explicit confirmation, and never widens terminal deletion', () => {
    const source = read('src/pages/Quarantine/index.tsx');
    assert.match(source, /record\.state === 'active' \|\| record\.state === 'purging'/);
    assert.match(source, /\) && isAdmin && \(/);
    assert.match(source, /清理缺失文件记录/);
    assert.match(source, /cleanupMissingRecordMutation\.mutateAsync\(target\.id\)/);
    assert.match(source, /onConfirm=\{\(\) => \{ void handleConfirmMissingCleanup\(\); \}\}/);
    assert.match(source, /确认仅删除数据库记录/);
    assert.match(source, /不会删除任何文件/);
    assert.match(source, /isSafeMode \|\| !allowDelete/);
    assert.match(source, /\['restored', 'purged', 'abandoned', 'conflict'\]\.includes\(record\.state\)/);
  });

  test('shows read-only filesystem evidence without lifting transactional blockers', () => {
    const source = read('src/pages/Quarantine/index.tsx');
    const types = read('src/types/quarantine.ts');
    assert.match(source, /payload_path_observation/);
    assert.match(source, /transaction_evidence_observation/);
    assert.match(source, /不证明事务完成/);
    assert.match(source, /不会放宽事务型记录的清理保护/);
    assert.match(types, /observation_is_cleanup_authority\?: false/);
    assert.match(source, /quarantineApi\.recoveryDiagnostic\(entryId\)/);
    assert.match(source, /cleanupMissingRecordMutation\.mutateAsync\(target\.id\)/);
  });

  test('never offers frozen or unverifiable purging cleanup even after public file deletion', () => {
    const legacy: QuarantineRecoveryDiagnostic = {
      id: 1106, state: 'purging', tx_phase: null, transaction_mode: null,
      has_authoritative_anchor: false, active_attempt_generation: 0,
      payload_path_observation: 'absent', transaction_evidence_observation: 'absent',
      work_job_id: null, work_job_status: null, work_job_error_code: null,
      plan_id: null, plan_status: null, plan_item_state: null, last_error: null,
      reason: 'legacy_purge_requires_verification',
      guidance: '只读诊断', automatic_cleanup_performed: false,
    };
    assert.equal(canOfferMissingPurgingRecordConfirmation(legacy), true);
    assert.equal(canOfferMissingPurgingRecordConfirmation({
      ...legacy, id: 884, tx_phase: 'purging',
      transaction_mode: 'cross_storage_transactional', active_attempt_generation: 2,
      reason: 'transactional_purge_needs_authority',
    }), false);
    assert.equal(canOfferMissingPurgingRecordConfirmation({
      ...legacy, transaction_evidence_observation: 'present',
    }), false);
    assert.equal(canOfferMissingPurgingRecordConfirmation({
      ...legacy, payload_path_observation: 'indeterminate',
    }), false);
    assert.equal(canOfferMissingPurgingRecordConfirmation({
      ...legacy, payload_path_observation: undefined,
    }), false);
    assert.equal(canOfferMissingPurgingRecordConfirmation({
      ...legacy, state: 'active',
    }), false);
    assert.equal(canOfferMissingPurgingRecordConfirmation({
      ...legacy, has_authoritative_anchor: true,
    }), false);
  });

  test('localizes the exact frozen-transaction 409 while not masking other errors', () => {
    assert.equal(isFrozenMissingRecordConflict({
      status: 409,
      message: 'Quarantine entry #1106 has transactional/frozen evidence; use Worker recovery, never metadata cleanup',
    }), true);
    assert.equal(isFrozenMissingRecordConflict({ status: 409, message: 'A batch/quarantine Worker job is still active' }), false);
    assert.equal(isFrozenMissingRecordConflict({ status: 403, message: 'transactional/frozen evidence' }), false);
    const source = read('src/pages/Quarantine/index.tsx');
    assert.match(source, /await quarantineApi\.recoveryDiagnostic\(record\.id\)/);
    assert.match(source, /!canOfferMissingPurgingRecordConfirmation\(diagnostic\)/);
    assert.match(source, /setRecoveryDiagnostic\(diagnostic\)/);
    assert.match(source, /不能直接清理/);
    assert.match(source, /isFrozenMissingRecordConflict\(err\)/);
    assert.match(source, /void confirmMissingCleanup\(record\)/);
  });

  test('does not silently convert recovery diagnosis into destructive mutation', () => {
    const source = read('src/pages/Quarantine/index.tsx');
    assert.match(source, /quarantineApi\.recoveryDiagnostic\(entryId\)/);
    assert.match(source, /没有执行删除、状态重置或事务恢复/);
    assert.match(source, /安全校验未通过，记录已保留/);
    const client = read('src/api/quarantine.ts');
    assert.match(client, /\/missing-record\?confirmation=CLEANUP_MISSING_RECORD/);
    assert.match(client, /\/record\?confirmation=DELETE_RECORD/);
  });
});
