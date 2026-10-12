import test, { describe } from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  getIndexRemoveAvailability,
  getIndexPathStatePresentation,
} from '../src/components/indexes/index_lifecycle';
import { indexesApi } from '../src/api/domain';
import { api } from '../src/api/client';
import { IndexRoot } from '../src/types';

describe('Index Root Lifecycle: Policy Matrix & API Contract Tests', () => {
  describe('Policy Matrix: getIndexRemoveAvailability', () => {
    test('null or undefined root disallows deletion safely', () => {
      const resNull = getIndexRemoveAvailability(null);
      assert.strictEqual(resNull.canRemove, false);
      assert.strictEqual(resNull.reason, '无效的索引根目录');

      const resUndef = getIndexRemoveAvailability(undefined);
      assert.strictEqual(resUndef.canRemove, false);
    });

    test('active index job strictly disables remove capability', () => {
      const rootWithActiveJob: Partial<IndexRoot> = {
        id: 1,
        root: '/data/Test',
        has_active_job: true,
        active_job_id: 101,
        active_job_status: 'running',
        can_remove: false,
      };
      const res = getIndexRemoveAvailability(rootWithActiveJob);
      assert.strictEqual(res.canRemove, false);
      assert.ok(res.reason?.includes('未结束的索引任务'));
    });

    test('terminal index state or no active job allows remove capability', () => {
      const rootReady: Partial<IndexRoot> = {
        id: 2,
        root: '/data/Ready',
        has_active_job: false,
        active_job_id: null,
        active_job_status: null,
        can_remove: true,
      };
      const res = getIndexRemoveAvailability(rootReady);
      assert.strictEqual(res.canRemove, true);
      assert.strictEqual(res.reason, undefined);
    });
  });

  describe('Presentation Helper: getIndexPathStatePresentation', () => {
    test('available state maps to green success tag without warning tooltip', () => {
      const res = getIndexPathStatePresentation('available');
      assert.strictEqual(res.label, '可用');
      assert.strictEqual(res.color, 'success');
      assert.strictEqual(res.tooltip, undefined);
    });

    test('missing state maps to red error tag with truthful snapshot metadata explanation', () => {
      const res = getIndexPathStatePresentation('missing');
      assert.strictEqual(res.label, '目录不存在');
      assert.strictEqual(res.color, 'error');
      assert.ok(res.tooltip?.includes('不是实时文件系统结果'));
    });

    test('blocked state maps to orange warning tag with security boundary explanation', () => {
      const res = getIndexPathStatePresentation('blocked');
      assert.strictEqual(res.label, '访问已阻止');
      assert.strictEqual(res.color, 'warning');
      assert.ok(res.tooltip?.includes('ALLOWED_ROOTS'));
    });

    test('unknown state returns fallback default presentation', () => {
      const res = getIndexPathStatePresentation('unknown_status');
      assert.strictEqual(res.label, 'unknown_status');
      assert.strictEqual(res.color, 'default');
    });
  });

  describe('API Client: indexesApi.deleteIndex & createIndex Contract', () => {
    test('deleteIndex issues DELETE to exact /api/indexes/{id} endpoint', async () => {
      const originalDelete = api.delete;
      let calledUrl = '';

      api.delete = (async (url: string) => {
        calledUrl = url;
        return {
          deleted: true,
          id: 42,
          root: '/data/Test',
          deleted_indexed_paths: 120,
        };
      }) as any;

      try {
        const res = await indexesApi.deleteIndex(42);
        assert.strictEqual(calledUrl, '/api/indexes/42');
        assert.strictEqual(res.deleted, true);
        assert.strictEqual(res.deleted_indexed_paths, 120);
      } finally {
        api.delete = originalDelete;
      }
    });

    test('createIndex sends root payload and accepts enhanced response structure', async () => {
      const originalPost = api.post;
      let postUrl = '';
      let postPayload: any = null;

      api.post = (async (url: string, payload: any) => {
        postUrl = url;
        postPayload = payload;
        return {
          index_root_id: 15,
          work_job_id: 88,
          status: 'queued',
          root: '/data/Folder',
          created: true,
        };
      }) as any;

      try {
        const res = await indexesApi.createIndex('/data/Folder');
        assert.strictEqual(postUrl, '/api/indexes');
        assert.deepStrictEqual(postPayload, { root: '/data/Folder' });
        assert.strictEqual(res.index_root_id, 15);
        assert.strictEqual(res.work_job_id, 88);
        assert.strictEqual(res.created, true);
      } finally {
        api.post = originalPost;
      }
    });
  });

  describe('DirectoryPicker Integration Gate', () => {
    test('native Indexes create dialog binds DirectoryPicker without legacy AntD Form.Item', () => {
      const indexPath = resolve(__dirname, '../../src/pages/Indexes/index.tsx');
      const content = readFileSync(indexPath, 'utf-8');

      assert.ok(content.includes("import { DirectoryPicker } from '../../components/DirectoryPicker'"));
      assert.ok(content.includes('<DirectoryPicker multiple={false} allowManualInput={true}'));
      assert.ok(content.includes('value={rootDraft}'));
      assert.ok(content.includes('disabled={createMutation.isPending}'));
      assert.ok(content.includes('onChange={value =>'));
      assert.ok(content.includes('const root = rootDraft.trim()'));
      assert.ok(content.includes("if (!root.startsWith('/'))"));
      assert.ok(content.includes('await createMutation.mutateAsync(root)'));
      assert.ok(content.includes('ALLOWED_ROOTS'));
      assert.ok(content.includes('<Dialog.Content'));
      assert.ok(content.includes('onPointerDownOutside={event => event.preventDefault()}'));
      assert.doesNotMatch(content, /from ['"]antd['"]|@ant-design\/icons|<Form\.Item\b|<Input\b/);
    });
  });
});
