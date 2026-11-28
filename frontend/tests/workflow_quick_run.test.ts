import assert from 'node:assert/strict';
import test from 'node:test';

import {
  readPendingQuickRun, rememberPendingQuickRun, clearPendingQuickRun,
  getReviewedQuickRun, quickRunExecutionId, quickRunSubmissionUnknown,
} from '../src/components/workflows/workflowQuickRunState';
import type { WorkflowPreviewResponse } from '../src/types/workflow';

const selection = { workflowId: '42', revision: 3, directory: '/data/Photos/11月' };
const digest = '1'.repeat(64);
const preview: WorkflowPreviewResponse = {
  workflow_id: 42, revision: 3, workflow_revision: 3, definition_sha256: digest, workflow_mode: 'file',
  preview_source: 'index', live_filesystem_verified: false, compile_digest: digest,
  matched_count: 40, matched_bytes: 1000, planned_operations_count: 40, page: 1, page_size: 8, total_pages: 5,
  items: [], file_summary: { directory: selection.directory, operation_counts: { move: 28, rename: 11, quarantine: 1 } },
};

test('quick run accepts only the exact reviewed workflow revision and directory with its full summary', () => {
  assert.equal(getReviewedQuickRun(selection, preview), preview);
  assert.equal(getReviewedQuickRun({ ...selection, directory: '/data/Photos/12月' }, preview), null);
  assert.equal(getReviewedQuickRun({ ...selection, revision: 4 }, preview), null);
  assert.equal(getReviewedQuickRun({ ...selection, workflowId: '43' }, preview), null);
  assert.equal(getReviewedQuickRun(selection, { ...preview, file_summary: undefined }), null);
  assert.equal(getReviewedQuickRun(selection, { ...preview, compile_digest: 'corrupt' }), null);
});

test('an uncertain submission keeps the original request by account and execution scope', () => {
  const request = {
    revision: selection.revision, directory: selection.directory, expected_compile_digest: digest,
    request_id: '410675a0-c955-4f18-940f-055da2817142',
  };
  rememberPendingQuickRun('7', selection, request);
  assert.deepEqual(readPendingQuickRun('7', selection), request);
  assert.equal(readPendingQuickRun('8', selection), null);
  assert.equal(readPendingQuickRun('7', { ...selection, directory: '/data/Photos/12月' }), null);
  clearPendingQuickRun('7', selection);
  assert.equal(readPendingQuickRun('7', selection), null);
});

test('unknown HTTP outcomes use the same token, while definitive rejections require a new review', () => {
  for (const status of [undefined, 0, 408, 500, 504]) assert.equal(quickRunSubmissionUnknown(status), true);
  for (const status of [400, 401, 403, 409, 422]) assert.equal(quickRunSubmissionUnknown(status), false);
});

test('queued execution uses only an exact string task ID, even after interrupted preparation', () => {
  assert.equal(quickRunExecutionId({ execution_job_id: '9007199254740993' }), '9007199254740993');
  assert.equal(quickRunExecutionId({ execution_job_id: 9007199254740992 }), null);
  assert.equal(quickRunExecutionId({ execution_job_id: 'invalid' }), null);
});
