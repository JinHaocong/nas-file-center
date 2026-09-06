import test, { describe } from 'node:test';
import assert from 'node:assert';
import { isWorkflowPlanMetadata, WorkflowPlanMetadata } from '../src/types/workflow';
import { workflowApi } from '../src/api/workflows';
import { api } from '../src/api/client';

describe('Gate5-C Stale Plan Rebuild Contract & Guard Tests', () => {
  describe('isWorkflowPlanMetadata Type Guard (Erratum E4)', () => {
    const validMetadata: WorkflowPlanMetadata = {
      source: 'workflow',
      workflow_id: 10,
      workflow_name: 'Test Workflow',
      workflow_revision: 2,
      definition_sha256: 'a'.repeat(64),
      compile_digest: 'b'.repeat(64),
      runtime_inputs: {
        root_ids: [1, 2],
      },
      compile_context: {},
      matched_count: 5,
      matched_bytes: 1024,
    };

    test('accepts valid workflow plan metadata object', () => {
      assert.strictEqual(isWorkflowPlanMetadata(validMetadata), true);
    });

    test('accepts valid workflow plan metadata as JSON string', () => {
      const jsonStr = JSON.stringify(validMetadata);
      assert.strictEqual(isWorkflowPlanMetadata(jsonStr), true);
    });

    test('rejects non-workflow plan metadata (e.g. manual, dedupe)', () => {
      const manualMeta = { ...validMetadata, source: 'manual' };
      assert.strictEqual(isWorkflowPlanMetadata(manualMeta), false);

      const emptyMeta = {};
      assert.strictEqual(isWorkflowPlanMetadata(emptyMeta), false);
      assert.strictEqual(isWorkflowPlanMetadata(null), false);
      assert.strictEqual(isWorkflowPlanMetadata(undefined), false);
    });

    test('rejects invalid or missing workflow_id', () => {
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, workflow_id: 0 }), false);
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, workflow_id: -1 }), false);
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, workflow_id: '10' as any }), false);
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, workflow_id: null as any }), false);
    });

    test('rejects invalid or missing workflow_revision', () => {
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, workflow_revision: 0 }), false);
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, workflow_revision: -1 }), false);
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, workflow_revision: '2' as any }), false);
    });

    test('rejects definition_sha256 that is not 64 chars', () => {
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, definition_sha256: 'too_short' }), false);
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, definition_sha256: 'a'.repeat(63) }), false);
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, definition_sha256: 'a'.repeat(65) }), false);
    });

    test('rejects compile_digest that is not 64 chars', () => {
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, compile_digest: 'invalid_digest' }), false);
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, compile_digest: 'b'.repeat(63) }), false);
      assert.strictEqual(isWorkflowPlanMetadata({ ...validMetadata, compile_digest: 'b'.repeat(65) }), false);
    });

    test('rejects empty or invalid root_ids in runtime_inputs', () => {
      assert.strictEqual(
        isWorkflowPlanMetadata({
          ...validMetadata,
          runtime_inputs: { root_ids: [] },
        }),
        false
      );
      assert.strictEqual(
        isWorkflowPlanMetadata({
          ...validMetadata,
          runtime_inputs: { root_ids: ['1' as any] },
        }),
        false
      );
      assert.strictEqual(
        isWorkflowPlanMetadata({
          ...validMetadata,
          runtime_inputs: { root_ids: [0] },
        }),
        false
      );
      assert.strictEqual(
        isWorkflowPlanMetadata({
          ...validMetadata,
          runtime_inputs: {} as any,
        }),
        false
      );
    });
  });

  describe('Rebuild Plan API Contracts', () => {
    test('rebuildPlanPreview post contract with defaults', async () => {
      let capturedUrl = '';
      let capturedBody: any = null;
      const origPost = api.post;
      api.post = (async (url: string, body: any) => {
        capturedUrl = url;
        capturedBody = body;
        return {
          source_plan_id: 100,
          workflow_id: 5,
          workflow_revision: 1,
          compile_digest: 'd'.repeat(64),
          items: [],
        };
      }) as any;

      try {
        await workflowApi.rebuildPlanPreview(100, {
          page: 2,
          page_size: 20,
          only_changed: true,
        });
        assert.strictEqual(capturedUrl, '/api/plans/100/rebuild-preview');
        assert.strictEqual(capturedBody.page, 2);
        assert.strictEqual(capturedBody.page_size, 20);
        assert.strictEqual(capturedBody.only_changed, true);

        // Default empty call
        await workflowApi.rebuildPlanPreview(100);
        assert.strictEqual(capturedUrl, '/api/plans/100/rebuild-preview');
        assert.deepStrictEqual(capturedBody, {});
      } finally {
        api.post = origPost;
      }
    });

    test('rebuildPlan creates new draft plan with expected_compile_digest', async () => {
      let capturedUrl = '';
      let capturedBody: any = null;
      const origPost = api.post;
      api.post = (async (url: string, body: any) => {
        capturedUrl = url;
        capturedBody = body;
        return {
          id: 201,
          plan_id: 201,
          name: body.plan_name || 'Rebuild Draft',
          status: 'draft',
          rebuild_of_plan_id: 100,
          compile_digest: body.expected_compile_digest,
        };
      }) as any;

      try {
        const result = await workflowApi.rebuildPlan(100, {
          expected_compile_digest: 'e'.repeat(64),
          plan_name: 'Custom Rebuild Plan Name',
        });
        assert.strictEqual(capturedUrl, '/api/plans/100/rebuild');
        assert.strictEqual(capturedBody.expected_compile_digest, 'e'.repeat(64));
        assert.strictEqual(capturedBody.plan_name, 'Custom Rebuild Plan Name');
        assert.strictEqual(result.id, 201);
        assert.strictEqual(result.status, 'draft');
        assert.strictEqual(result.rebuild_of_plan_id, 100);
      } finally {
        api.post = origPost;
      }
    });
  });
});
