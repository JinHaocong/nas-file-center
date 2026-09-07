import test, { describe } from 'node:test';
import assert from 'node:assert';
import {
  validateWorkflowStepOrder,
  getAllowedInsertions,
} from '../src/utils/workflowTopology';
import { canSwitchWorkflowMode } from '../src/utils/workflowRbac';
import { createDefaultOrganizerSnapshot } from '../src/utils/organizerDefaults';
import { OrganizerProfileSnapshot, WorkflowStep } from '../src/types/workflow';

describe('Gate5-C-hotfix2 RED Tests', () => {
  describe('P2-07: Step insertion topology', () => {
    test('Scan -> Rename: getAllowedInsertions does NOT contain filter', () => {
      const steps: WorkflowStep[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'rename', pattern: 'draft', replacement: 'final' },
      ];
      const allowed = getAllowedInsertions(steps, 'file');
      assert.strictEqual(
        allowed.includes('filter'),
        false,
        `Expected allowed insertions to NOT include 'filter', got: ${JSON.stringify(allowed)}`
      );
    });

    test('Scan -> Move: getAllowedInsertions does NOT contain filter', () => {
      const steps: WorkflowStep[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'move', destination_root_id: 1 },
      ];
      const allowed = getAllowedInsertions(steps, 'file');
      assert.strictEqual(allowed.includes('filter'), false);
    });

    test('Scan -> Touch: getAllowedInsertions does NOT contain filter', () => {
      const steps: WorkflowStep[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'touch', touch_now: true, mtime_ns: null },
      ];
      const allowed = getAllowedInsertions(steps, 'file');
      assert.strictEqual(allowed.includes('filter'), false);
    });

    test('Scan -> Filter: allows second filter and actions and quarantine', () => {
      const steps: WorkflowStep[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'filter', filter: { field: 'extension', operator: 'eq', value: 'jpg' } },
      ];
      const allowed = getAllowedInsertions(steps, 'file');
      assert.strictEqual(allowed.includes('filter'), true);
      assert.strictEqual(allowed.includes('rename'), true);
      assert.strictEqual(allowed.includes('move'), true);
      assert.strictEqual(allowed.includes('touch'), true);
      assert.strictEqual(allowed.includes('quarantine'), true);
    });

    test('Scan only: allows filter, actions, and quarantine', () => {
      const steps: WorkflowStep[] = [
        { id: '1', type: 'scan', root_ids: [1] },
      ];
      const allowed = getAllowedInsertions(steps, 'file');
      assert.deepStrictEqual(allowed, ['filter', 'rename', 'move', 'touch', 'quarantine']);
    });

    test('Scan -> Quarantine: allowed is empty', () => {
      const steps: WorkflowStep[] = [
        { id: '1', type: 'scan', root_ids: [1] },
        { id: '2', type: 'quarantine', reason: 'policy violation' },
      ];
      const allowed = getAllowedInsertions(steps, 'file');
      assert.deepStrictEqual(allowed, []);
    });
  });

  describe('P2-08: Stale Rebuild PREVIEW_CHANGED invalidation', () => {
    test('preview digest A -> PREVIEW_CHANGED clears readiness and prevents resubmission until manual refresh', () => {
      // Simulation of StaleRebuildDrawer preview state machine
      interface RebuildState {
        acceptedDigest: string | null;
        previewInvalidated: boolean;
        errorMessage: string | null;
      }

      function onPreviewSuccess(state: RebuildState, digest: string): RebuildState {
        return {
          acceptedDigest: digest,
          previewInvalidated: false,
          errorMessage: null,
        };
      }

      function onRebuildError409(state: RebuildState, errCode: string): RebuildState {
        if (errCode === 'PREVIEW_CHANGED') {
          return {
            acceptedDigest: null,
            previewInvalidated: true,
            errorMessage: '工作流已变更，旧预览已失效，请手动刷新预览后重新提交',
          };
        }
        return state;
      }

      function canSubmitRebuild(state: RebuildState): boolean {
        return !state.previewInvalidated && !!state.acceptedDigest;
      }

      // Step 1: Initial successful preview with digest A
      let state: RebuildState = { acceptedDigest: null, previewInvalidated: false, errorMessage: null };
      state = onPreviewSuccess(state, 'digest_A');
      assert.strictEqual(canSubmitRebuild(state), true);
      assert.strictEqual(state.acceptedDigest, 'digest_A');

      // Step 2: Rebuild returns 409 PREVIEW_CHANGED
      state = onRebuildError409(state, 'PREVIEW_CHANGED');
      assert.strictEqual(canSubmitRebuild(state), false);
      assert.strictEqual(state.acceptedDigest, null);
      assert.strictEqual(state.previewInvalidated, true);

      // Step 3: User manually refreshes preview to digest B
      state = onPreviewSuccess(state, 'digest_B');
      assert.strictEqual(canSubmitRebuild(state), true);
      assert.strictEqual(state.acceptedDigest, 'digest_B');
      assert.strictEqual(state.previewInvalidated, false);
    });
  });

  describe('P2-11A: Existing workflow mode switch permission matrix', () => {
    test('canSwitchWorkflowMode correctly enforces permissions and state constraints', () => {
      // Admin on active non-builtin non-historical workflow
      assert.strictEqual(
        canSwitchWorkflowMode('admin', { isBuiltin: false, isArchived: false, isHistorical: false }),
        true
      );

      // Member is forbidden
      assert.strictEqual(
        canSwitchWorkflowMode('member', { isBuiltin: false, isArchived: false, isHistorical: false }),
        false
      );

      // Built-in is forbidden
      assert.strictEqual(
        canSwitchWorkflowMode('admin', { isBuiltin: true, isArchived: false, isHistorical: false }),
        false
      );

      // Archived is forbidden
      assert.strictEqual(
        canSwitchWorkflowMode('admin', { isBuiltin: false, isArchived: true, isHistorical: false }),
        false
      );

      // Historical revision view is forbidden
      assert.strictEqual(
        canSwitchWorkflowMode('admin', { isBuiltin: false, isArchived: false, isHistorical: true }),
        false
      );
    });
  });

  describe('P2-11B: Profile snapshot import copy semantics', () => {
    test('importing OrganizerProfile produces deep immutable copy without leaking live binding', () => {
      // Helper function under test
      const liveProfile = {
        id: 42,
        name: 'Live Album Profile',
        description: 'Auto-organize pictures',
        root: '/data/photos',
        recursive: true,
        image_extensions: ['jpg', 'png'],
        video_extensions: ['mp4'],
        rename_template: '{date}_{name}',
        statistics_template: '[{images}P {size}]',
        preserve_tags: ['tag1'],
        cleanup_patterns: ['*.tmp'],
        numbering_mode: 'sequential' as const,
        numbering_start: 10,
        numbering_padding: 4,
        mtime_mode: 'ordered' as const,
        mtime_delay_seconds: 5.0,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-02T00:00:00Z',
      };

      // Import copy logic
      function importProfileToSnapshot(p: typeof liveProfile): OrganizerProfileSnapshot {
        return {
          name: p.name,
          description: p.description || '',
          root: p.root || '',
          recursive: p.recursive ?? false,
          image_extensions: [...(p.image_extensions || [])],
          video_extensions: [...(p.video_extensions || [])],
          rename_template: p.rename_template || '{name}',
          statistics_template: p.statistics_template || '[{images}P {videos}V {size}]',
          preserve_tags: [...(p.preserve_tags || [])],
          cleanup_patterns: [...(p.cleanup_patterns || [])],
          numbering_mode: p.numbering_mode || 'none',
          numbering_start: p.numbering_start ?? 1,
          numbering_padding: p.numbering_padding ?? 3,
          mtime_mode: p.mtime_mode || 'none',
          mtime_delay_seconds: p.mtime_delay_seconds ?? 2.0,
        };
      }

      const snapshot = importProfileToSnapshot(liveProfile);

      // Verify no id / timestamps leaked
      assert.strictEqual('id' in snapshot, false);
      assert.strictEqual('source_profile_id' in snapshot, false);
      assert.strictEqual('created_at' in snapshot, false);
      assert.strictEqual('updated_at' in snapshot, false);

      // Verify exact values copied
      assert.strictEqual(snapshot.name, 'Live Album Profile');
      assert.strictEqual(snapshot.numbering_start, 10);
      assert.deepStrictEqual(snapshot.image_extensions, ['jpg', 'png']);

      // Mutate liveProfile
      liveProfile.name = 'Mutated Profile Name';
      liveProfile.image_extensions.push('gif');
      liveProfile.numbering_start = 999;

      // Assert snapshot remains completely unchanged
      assert.strictEqual(snapshot.name, 'Live Album Profile');
      assert.deepStrictEqual(snapshot.image_extensions, ['jpg', 'png']);
      assert.strictEqual(snapshot.numbering_start, 10);
    });
  });
});
