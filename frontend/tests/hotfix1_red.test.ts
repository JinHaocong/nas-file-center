import test, { describe } from 'node:test';
import assert from 'node:assert';
import { isWorkflowPlanMetadata } from '../src/types/workflow';
import { createDefaultOrganizerSnapshot } from '../src/utils/organizerDefaults';
import { applyLiteralRename } from '../src/utils/workflowRename';
import {
  validateWorkflowStepOrder,
  getAllowedInsertions,
  canMoveStep,
  canDeleteStep,
} from '../src/utils/workflowTopology';
import {
  canCreateWorkflow,
  canSaveRevision,
  canArchiveWorkflow,
  canRollbackWorkflow,
  canPreviewWorkflow,
  canGenerateDraft,
} from '../src/utils/workflowRbac';
import {
  transitionPreviewState,
  WorkflowPreviewState,
} from '../src/utils/workflowPreviewMachine';
import {
  ALLOWED_OPERATORS_BY_FIELD,
  normalizeExtension,
  validateFilterLimits,
} from '../src/utils/filterMatrix';
import { workflowApi } from '../src/api/workflows';
import { api } from '../src/api/client';

describe('Gate5-C-hotfix1 RED Tests', () => {
  describe('P1-01: Organizer Canonical Defaults', () => {
    test('createDefaultOrganizerSnapshot returns exact canonical defaults', () => {
      const snap = createDefaultOrganizerSnapshot('Minimal');
      assert.strictEqual(snap.name, 'Minimal');
      assert.strictEqual(snap.recursive, false);
      assert.deepStrictEqual(snap.image_extensions, ['jpg', 'jpeg', 'png', 'webp']);
      assert.deepStrictEqual(snap.video_extensions, ['mp4', 'mov', 'mkv']);
      assert.strictEqual(snap.rename_template, '{name}');
      assert.strictEqual(snap.statistics_template, '[{images}P {videos}V {size}]');
      assert.deepStrictEqual(snap.preserve_tags, []);
      assert.deepStrictEqual(snap.cleanup_patterns, []);
      assert.strictEqual(snap.numbering_mode, 'none');
      assert.strictEqual(snap.numbering_start, 1);
      assert.strictEqual(snap.numbering_padding, 3);
      assert.strictEqual(snap.mtime_mode, 'none');
      assert.strictEqual(snap.mtime_delay_seconds, 2.0);
    });

    test('default snapshot rename produces zero changes on Album (Album -> Album)', () => {
      const snap = createDefaultOrganizerSnapshot('Test');
      // With rename_template = '{name}' and numbering_mode = 'none', Album remains Album
      const folderName = 'Album';
      const rendered = snap.rename_template.replace('{name}', folderName);
      assert.strictEqual(rendered, folderName);
    });
  });

  describe('P1-02: Rename Literal Semantics', () => {
    test('applyLiteralRename performs substring replacement without regex evaluation', () => {
      // Literal match: IMG_(\\d+) should NOT match IMG_123
      const res1 = applyLiteralRename('IMG_123.jpg', 'IMG_(\\d+)', 'PHOTO_$1');
      assert.strictEqual(res1, 'IMG_123.jpg');

      // Literal match for exact text with regex special chars
      const res2 = applyLiteralRename('a[0-9]+b.txt', '[0-9]+', 'NUM');
      assert.strictEqual(res2, 'aNUMb.txt');

      // Replacement $1 is not expanded as capture group
      const res3 = applyLiteralRename('doc_1.txt', 'doc', '$1_file');
      assert.strictEqual(res3, '$1_file_1.txt');
    });
  });

  describe('P2-01: Workflow Topology Rules', () => {
    test('File mode requires exactly one Scan at index 0', () => {
      const validSteps: any[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'filter', filter: { field: 'extension', operator: 'eq', value: 'txt' } },
        { id: '3', type: 'rename', pattern: 'a', replacement: 'b' },
      ];
      assert.strictEqual(validateWorkflowStepOrder(validSteps, 'file').valid, true);

      // Missing scan
      assert.strictEqual(validateWorkflowStepOrder([validSteps[1], validSteps[2]], 'file').valid, false);

      // Scan not at index 0
      assert.strictEqual(validateWorkflowStepOrder([validSteps[1], validSteps[0]], 'file').valid, false);

      // Multiple scans
      assert.strictEqual(validateWorkflowStepOrder([validSteps[0], validSteps[0]], 'file').valid, false);
    });

    test('File mode requires Filters before Actions', () => {
      const invalidOrder: any[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'rename', pattern: 'a', replacement: 'b' },
        { id: '3', type: 'filter', filter: { field: 'extension', operator: 'eq', value: 'txt' } },
      ];
      const res = validateWorkflowStepOrder(invalidOrder, 'file');
      assert.strictEqual(res.valid, false);
      assert.match(res.error || '', /Filter/i);
    });

    test('File mode Quarantine must be terminal', () => {
      const withQuarantineMiddle: any[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'quarantine', reason: 'bad' },
        { id: '3', type: 'touch', touch_now: true, mtime_ns: null },
      ];
      const res = validateWorkflowStepOrder(withQuarantineMiddle, 'file');
      assert.strictEqual(res.valid, false);

      const withQuarantineTerminal: any[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'touch', touch_now: true, mtime_ns: null },
        { id: '3', type: 'quarantine', reason: 'bad' },
      ];
      assert.strictEqual(validateWorkflowStepOrder(withQuarantineTerminal, 'file').valid, true);
    });

    test('Organizer mode requires exactly Scan -> Organize', () => {
      const validOrg: any[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'organize', profile_snapshot: createDefaultOrganizerSnapshot('Org') },
      ];
      assert.strictEqual(validateWorkflowStepOrder(validOrg, 'organizer').valid, true);

      // Rejects Filter or Rename
      const invalidOrg: any[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'rename', pattern: 'a', replacement: 'b' },
        { id: '3', type: 'organize', profile_snapshot: createDefaultOrganizerSnapshot('Org') },
      ];
      assert.strictEqual(validateWorkflowStepOrder(invalidOrg, 'organizer').valid, false);
    });

    test('getAllowedInsertions and step manipulation restrictions', () => {
      const orgSteps: any[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'organize', profile_snapshot: createDefaultOrganizerSnapshot('Org') },
      ];
      assert.deepStrictEqual(getAllowedInsertions(orgSteps, 'organizer'), []);

      const fileWithQuarantine: any[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'quarantine', reason: 'bad' },
      ];
      assert.deepStrictEqual(getAllowedInsertions(fileWithQuarantine, 'file'), []);

      // Scan cannot be deleted
      assert.strictEqual(canDeleteStep(fileWithQuarantine, 0, 'file'), false);
      assert.strictEqual(canDeleteStep(fileWithQuarantine, 1, 'file'), true);

      // Scan cannot move down
      assert.strictEqual(canMoveStep(fileWithQuarantine, 0, 'down', 'file'), false);
    });
  });

  describe('P2-02: Explicit Preview State Machine', () => {
    test('state transitions and 409 PREVIEW_CHANGED handling', () => {
      let state: WorkflowPreviewState = 'CLEAN_SAVED';

      state = transitionPreviewState(state, { type: 'DIRTY_CHANGE', isDirty: true });
      assert.strictEqual(state, 'EDITING_DIRTY');

      state = transitionPreviewState(state, { type: 'DIRTY_CHANGE', isDirty: false });
      assert.strictEqual(state, 'SAVED_PREVIEW_REQUIRED');

      state = transitionPreviewState(state, { type: 'START_PREVIEW' });
      assert.strictEqual(state, 'PREVIEWING');

      state = transitionPreviewState(state, { type: 'PREVIEW_SUCCESS', compileDigest: 'd'.repeat(64) });
      assert.strictEqual(state, 'PREVIEW_READY');

      // Root changes invalidate preview
      state = transitionPreviewState(state, { type: 'ROOTS_CHANGE' });
      assert.strictEqual(state, 'PREVIEW_STALE');

      // 409 error transitions to PREVIEW_STALE without auto-retry
      state = transitionPreviewState('PREVIEW_READY', { type: 'PREVIEW_CHANGED_ERROR' });
      assert.strictEqual(state, 'PREVIEW_STALE');
    });
  });

  describe('P2-03: RBAC & Archived Capability Matrix', () => {
    test('admin vs member capabilities', () => {
      // Active workflow
      assert.strictEqual(canCreateWorkflow('admin', false), true);
      assert.strictEqual(canCreateWorkflow('member', false), false);

      assert.strictEqual(canSaveRevision('admin', false), true);
      assert.strictEqual(canSaveRevision('member', false), false);

      assert.strictEqual(canArchiveWorkflow('admin', false), true);
      assert.strictEqual(canArchiveWorkflow('member', false), false);

      assert.strictEqual(canRollbackWorkflow('admin', false), true);
      assert.strictEqual(canRollbackWorkflow('member', false), false);

      assert.strictEqual(canPreviewWorkflow(false), true);
      assert.strictEqual(canGenerateDraft(false), true);

      // Archived workflow disables mutating actions
      assert.strictEqual(canSaveRevision('admin', true), false);
      assert.strictEqual(canRollbackWorkflow('admin', true), false);
      assert.strictEqual(canPreviewWorkflow(true), false);
      assert.strictEqual(canGenerateDraft(true), false);
    });
  });

  describe('P2-04: Historical Revision API', () => {
    test('workflowApi.getRevision calls /api/workflows/{id}/revisions/{revision}', async () => {
      let capturedUrl = '';
      const origGet = api.get;
      api.get = (async (url: string) => {
        capturedUrl = url;
        return {
          id: 10,
          workflow_id: 3,
          revision: 2,
          definition: {},
          definition_sha256: 'a'.repeat(64),
          created_at: new Date().toISOString(),
        };
      }) as any;

      try {
        await workflowApi.getRevision(3, 2);
        assert.strictEqual(capturedUrl, '/api/workflows/3/revisions/2');
      } finally {
        api.get = origGet;
      }
    });
  });

  describe('P2-05: Filter Operator Matrix & Limits', () => {
    test('matrix strictly matches Gate5-A allowed operators', () => {
      assert.deepStrictEqual(ALLOWED_OPERATORS_BY_FIELD.path, [
        'eq', 'neq', 'contains', 'startswith', 'endswith', 'in', 'nin',
      ]);
      assert.deepStrictEqual(ALLOWED_OPERATORS_BY_FIELD.name, [
        'eq', 'neq', 'contains', 'startswith', 'endswith', 'in', 'nin',
      ]);
      assert.deepStrictEqual(ALLOWED_OPERATORS_BY_FIELD.extension, [
        'eq', 'neq', 'in', 'nin',
      ]);
      assert.deepStrictEqual(ALLOWED_OPERATORS_BY_FIELD.size, [
        'eq', 'neq', 'gt', 'gte', 'lt', 'lte',
      ]);
      assert.deepStrictEqual(ALLOWED_OPERATORS_BY_FIELD.mtime, [
        'eq', 'neq', 'gt', 'gte', 'lt', 'lte',
      ]);
      assert.deepStrictEqual(ALLOWED_OPERATORS_BY_FIELD.media_type, [
        'eq', 'neq', 'in', 'nin',
      ]);
    });

    test('normalizeExtension removes leading dot and lowercases', () => {
      assert.strictEqual(normalizeExtension('.JPG'), 'jpg');
      assert.strictEqual(normalizeExtension('PNG'), 'png');
      assert.strictEqual(normalizeExtension('  .tar.gz '), 'tar.gz');
    });

    test('enforces limits (depth <= 5, children <= 50, leaves <= 200)', () => {
      assert.strictEqual(validateFilterLimits({ depth: 5, children: 50, leaves: 200 }), true);
      assert.strictEqual(validateFilterLimits({ depth: 6, children: 10, leaves: 10 }), false);
      assert.strictEqual(validateFilterLimits({ depth: 2, children: 51, leaves: 10 }), false);
      assert.strictEqual(validateFilterLimits({ depth: 2, children: 10, leaves: 201 }), false);
    });
  });

  describe('P2-06: Strict Metadata Guard Edge Cases', () => {
    const validMeta = {
      source: 'workflow',
      workflow_id: 1,
      workflow_revision: 1,
      definition_sha256: 'a'.repeat(64),
      compile_digest: 'b'.repeat(64),
      runtime_inputs: {
        root_ids: [1],
      },
    };

    test('accepts valid metadata', () => {
      assert.strictEqual(isWorkflowPlanMetadata(validMeta), true);
    });

    test('rejects float workflow_id (1.5)', () => {
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMeta, workflow_id: 1.5 }), false);
    });

    test('rejects NaN workflow_id', () => {
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMeta, workflow_id: NaN }), false);
    });

    test('rejects Infinity workflow_id', () => {
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMeta, workflow_id: Infinity }), false);
    });

    test('rejects float workflow_revision (2.7)', () => {
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMeta, workflow_revision: 2.7 }), false);
    });

    test('rejects 64-char non-hex definition_sha256', () => {
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMeta, definition_sha256: 'g'.repeat(64) }), false);
    });

    test('rejects 64-char non-hex compile_digest', () => {
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMeta, compile_digest: 'z'.repeat(64) }), false);
    });

    test('rejects empty root_ids list', () => {
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMeta, runtime_inputs: { root_ids: [] } }), false);
    });

    test('rejects root_ids with float or non-integer', () => {
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMeta, runtime_inputs: { root_ids: [1, 2.5] } }), false);
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMeta, runtime_inputs: { root_ids: [NaN] } }), false);
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMeta, runtime_inputs: { root_ids: [0] } }), false);
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMeta, runtime_inputs: { root_ids: [-1] } }), false);
    });
  });
});
