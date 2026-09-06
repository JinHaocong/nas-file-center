import test, { describe } from 'node:test';
import assert from 'node:assert';
import {
  isFilterLeafNode,
  isFilterAndOrNode,
  isFilterNotNode,
  FilterLeafNode,
  FilterAndOrNode,
  FilterNotNode,
  ScanStep,
  TouchStep,
  OrganizerProfileSnapshot,
  WorkflowDefinition,
} from '../src/types/workflow';
import { workflowApi } from '../src/api/workflows';
import { getStructuredApiError } from '../src/api/errors';
import { api } from '../src/api/client';

describe('Gate5-C Frontend Workflows Contract & Type Tests', () => {
  describe('Filter AST Types & Guards', () => {
    test('isFilterLeafNode correctly detects leaf node', () => {
      const leaf: FilterLeafNode = {
        field: 'extension',
        operator: 'eq',
        value: 'jpg',
        case_sensitive: false,
      };
      assert.strictEqual(isFilterLeafNode(leaf), true);
      assert.strictEqual(isFilterAndOrNode(leaf), false);
      assert.strictEqual(isFilterNotNode(leaf), false);
    });

    test('isFilterAndOrNode correctly detects AND/OR composite nodes', () => {
      const andNode: FilterAndOrNode = {
        op: 'and',
        children: [
          { field: 'extension', operator: 'eq', value: 'jpg' },
          { field: 'size', operator: 'gt', value: 1024 },
        ],
      };
      assert.strictEqual(isFilterAndOrNode(andNode), true);
      assert.strictEqual(isFilterLeafNode(andNode), false);

      const orNode: FilterAndOrNode = {
        op: 'or',
        children: [{ field: 'extension', operator: 'eq', value: 'png' }],
      };
      assert.strictEqual(isFilterAndOrNode(orNode), true);
    });

    test('isFilterNotNode correctly detects NOT node', () => {
      const notNode: FilterNotNode = {
        op: 'not',
        child: { field: 'name', operator: 'startswith', value: '.' },
      };
      assert.strictEqual(isFilterNotNode(notNode), true);
      assert.strictEqual(isFilterLeafNode(notNode), false);
      assert.strictEqual(isFilterAndOrNode(notNode), false);
    });
  });

  describe('Step Definitions Contract', () => {
    test('ScanStep supports optional subpath without null', () => {
      const stepWithSubpath: ScanStep = {
        id: 's1',
        type: 'scan',
        root_ids: [1, 2],
        subpath: 'photos/2026',
      };
      assert.strictEqual(stepWithSubpath.subpath, 'photos/2026');

      const stepWithoutSubpath: ScanStep = {
        id: 's2',
        type: 'scan',
        root_ids: [1],
      };
      assert.strictEqual(stepWithoutSubpath.subpath, undefined);
    });

    test('TouchStep supports touch_now and mtime_ns', () => {
      const stepNow: TouchStep = {
        id: 't1',
        type: 'touch',
        touch_now: true,
        mtime_ns: null,
      };
      assert.strictEqual(stepNow.touch_now, true);
      assert.strictEqual(stepNow.mtime_ns, null);

      const stepFixed: TouchStep = {
        id: 't2',
        type: 'touch',
        touch_now: false,
        mtime_ns: 1772841600000000000,
      };
      assert.strictEqual(stepFixed.touch_now, false);
      assert.strictEqual(stepFixed.mtime_ns, 1772841600000000000);
    });

    test('OrganizerProfileSnapshot includes canonical 14 fields', () => {
      const snapshot: OrganizerProfileSnapshot = {
        name: 'Profile 1',
        description: 'Test Description',
        root: '/nas/photos',
        recursive: true,
        image_extensions: ['jpg', 'png'],
        video_extensions: ['mp4'],
        rename_template: '{name} {statistics}',
        statistics_template: '[{images}P {videos}V {size}]',
        preserve_tags: ['[精选]'],
        cleanup_patterns: ['\\[\\d+P\\]'],
        numbering_mode: 'sequential',
        numbering_start: 1,
        numbering_padding: 3,
        mtime_mode: 'ordered',
        mtime_delay_seconds: 2.5,
      };
      assert.strictEqual(snapshot.name, 'Profile 1');
      assert.strictEqual(snapshot.numbering_mode, 'sequential');
      assert.strictEqual(snapshot.mtime_mode, 'ordered');
    });
  });

  describe('Workflow API Client Calls', () => {
    test('listWorkflows passes include_archived flag', async () => {
      let capturedUrl = '';
      const origGet = api.get;
      api.get = (async (url: string) => {
        capturedUrl = url;
        return [];
      }) as any;

      try {
        await workflowApi.listWorkflows(false);
        assert.strictEqual(capturedUrl, '/api/workflows?include_archived=false');

        await workflowApi.listWorkflows(true);
        assert.strictEqual(capturedUrl, '/api/workflows?include_archived=true');
      } finally {
        api.get = origGet;
      }
    });

    test('archiveWorkflow passes expected_current_revision query param', async () => {
      let capturedUrl = '';
      const origDelete = api.delete;
      api.delete = (async (url: string) => {
        capturedUrl = url;
        return { status: 'ok', archived: true };
      }) as any;

      try {
        await workflowApi.archiveWorkflow(12, 3);
        assert.strictEqual(capturedUrl, '/api/workflows/12?expected_current_revision=3');
      } finally {
        api.delete = origDelete;
      }
    });

    test('previewWorkflow and generatePlan request contract', async () => {
      let capturedPostUrl = '';
      let capturedPostBody: any = null;
      const origPost = api.post;
      api.post = (async (url: string, body: any) => {
        capturedPostUrl = url;
        capturedPostBody = body;
        if (url.endsWith('/preview')) {
          return {
            workflow_id: 1,
            revision: 1,
            compile_digest: 'a'.repeat(64),
            planned_operations_count: 5,
            items: [],
          };
        }
        return { plan_id: 100, plan_name: 'Test Plan' };
      }) as any;

      try {
        await workflowApi.previewWorkflow(1, {
          revision: 2,
          only_changed: false,
          runtime_inputs: { root_ids: [1, 2] },
        });
        assert.strictEqual(capturedPostUrl, '/api/workflows/1/preview');
        assert.strictEqual(capturedPostBody.only_changed, false);
        assert.deepStrictEqual(capturedPostBody.runtime_inputs, { root_ids: [1, 2] });

        await workflowApi.generatePlan(1, {
          expected_compile_digest: 'a'.repeat(64),
          plan_name: 'Custom Plan Name',
        });
        assert.strictEqual(capturedPostUrl, '/api/workflows/1/generate-plan');
        assert.strictEqual(capturedPostBody.expected_compile_digest, 'a'.repeat(64));
        assert.strictEqual(capturedPostBody.plan_name, 'Custom Plan Name');
      } finally {
        api.post = origPost;
      }
    });
  });

  describe('Structured API Error Parsing', () => {
    test('extracts structured error with code and details', () => {
      const apiErr = {
        status: 409,
        detail: {
          error: {
            code: 'PREVIEW_CHANGED',
            message: 'Compile digest has changed',
            details: { expected: '123', actual: '456' },
          },
        },
      };
      const parsed = getStructuredApiError(apiErr);
      assert.strictEqual(parsed.code, 'PREVIEW_CHANGED');
      assert.strictEqual(parsed.message, 'Compile digest has changed');
      assert.deepStrictEqual(parsed.details, { expected: '123', actual: '456' });
      assert.strictEqual(parsed.status, 409);
    });

    test('extracts WORKFLOW_ARCHIVED 409 correctly', () => {
      const apiErr = {
        status: 409,
        detail: {
          error: {
            code: 'WORKFLOW_ARCHIVED',
            message: 'Workflow 5 is archived',
          },
        },
      };
      const parsed = getStructuredApiError(apiErr);
      assert.strictEqual(parsed.code, 'WORKFLOW_ARCHIVED');
      assert.strictEqual(parsed.status, 409);
    });

    test('handles fallback string message', () => {
      const parsed = getStructuredApiError({ detail: 'Raw string error' });
      assert.strictEqual(parsed.message, 'Raw string error');
    });
  });
});
