import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  buildSchedulePayload, buildScheduleTarget, createDefaultScheduleDraft,
  draftFromSchedule, splitPatterns, TARGET_LABELS,
} from '../src/pages/Scheduler/schedulerModel';
import type { ScheduleItem } from '../src/types/scheduler';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const page = () => read('src/pages/Scheduler/index.tsx');
const editor = () => read('src/pages/Scheduler/ScheduleEditorModal.tsx');
const history = () => read('src/pages/Scheduler/ScheduleHistoryDrawer.tsx');

describe('Console v2 native Scheduler S4 semantics', () => {
  test('five target types retain their full original menu and model', () => {
    assert.deepEqual(Object.keys(TARGET_LABELS), [
      'index_root', 'fclones_scan', 'media_analysis', 'media_integrity_verification', 'workflow',
    ]);
    const s = editor();
    for (const name of ['index_root', 'fclones_scan', 'media_analysis', 'media_integrity_verification', 'workflow']) {
      assert.ok(read('src/pages/Scheduler/schedulerModel.ts').includes(name));
    }
    assert.ok(s.includes('Object.entries(TARGET_LABELS)'));
  });
  test('default scheduler form keeps safe preview, skip policies and browser timezone', () => {
    const d = createDefaultScheduleDraft('Asia/Shanghai');
    assert.equal(d.enabled, true);
    assert.equal(d.cron, '0 2 * * *');
    assert.equal(d.targetType, 'index_root');
    assert.equal(d.workflowAction, 'preview');
    assert.equal(d.scanIsolate, false);
    assert.equal(d.timezone, 'Asia/Shanghai');
  });
  test('cron and schedule name are required on native and typed payload boundary', () => {
    const d = createDefaultScheduleDraft();
    assert.throws(() => buildSchedulePayload(d, null), /请输入名称/);
    d.name = '  photos  '; d.indexRootId = '3';
    const v = buildSchedulePayload(d, null);
    assert.equal(v.name, 'photos');
    assert.equal(v.target.type, 'index_root');
    d.cron = '';
    assert.throws(() => buildSchedulePayload(d, null), /Cron/);
  });
  test('index root requires positive exact integer id', () => {
    const d = createDefaultScheduleDraft();
    for(const bad of ['', '0', '-2', '1.5', 'xyz', '9999999999999999999999']) {
      d.indexRootId = bad;
      assert.throws(() => buildScheduleTarget(d, null), /有效/);
    }
    d.indexRootId = '5';
    assert.deepEqual(buildScheduleTarget(d, null), { type: 'index_root', root_id: 5 });
  });
  test('scan target preserves roots, isolate, min size and comma/newline tag semantics', () => {
    const d = createDefaultScheduleDraft();
    d.targetType = 'fclones_scan';
    assert.throws(() => buildScheduleTarget(d, null), /扫描目录/);
    d.scanRoots = ['/data/a', '/data/b'];
    d.scanIsolate = true;
    d.scanMinSize = ' 10M ';
    d.scanNamePatterns = '*.mkv, *.mp4\n*.avi';
    d.scanExcludePatterns = ' sample*,  ';
    assert.deepEqual(splitPatterns(d.scanNamePatterns), ['*.mkv', '*.mp4', '*.avi']);
    assert.deepEqual(buildScheduleTarget(d, null), {
      type: 'fclones_scan', roots: ['/data/a', '/data/b'],
      isolate: true, min_size: '10M',
      name_patterns: ['*.mkv', '*.mp4', '*.avi'], exclude_patterns: ['sample*'],
    });
  });
  test('both media targets preserve exact selected root keys', () => {
    const d = createDefaultScheduleDraft();
    for (const type of ['media_analysis', 'media_integrity_verification'] as const) {
      d.targetType = type;
      assert.throws(() => buildScheduleTarget(d, null), /媒体根目录/);
      d.mediaRootKeys = ['/data/one'];
      assert.deepEqual(buildScheduleTarget(d, null), { type, root_keys: ['/data/one'] });
    }
  });
  test('utility fixed workflow can preview but cannot generate Draft', () => {
    const d = createDefaultScheduleDraft();
    d.targetType = 'workflow'; d.workflowId = '9';
    d.workflowRevision = 4; d.workflowSha = 'abc123';
    d.workflowAction = 'draft';
    assert.throws(() => buildScheduleTarget(d, 'utility'), /仅允许 Preview/);
    d.workflowAction = 'preview';
    assert.deepEqual(buildScheduleTarget(d, 'utility'), {
      type: 'workflow', workflow_id: 9, workflow_revision: 4,
      definition_sha256: 'abc123', action: 'preview', runtime_inputs: null,
    });
  });
  test('workflow target fails closed unless pinned revision/SHA and mode are verified', () => {
    const d = createDefaultScheduleDraft();
    d.targetType = 'workflow'; d.workflowId = '9';
    assert.throws(() => buildScheduleTarget(d, 'file'), /固定工作流 revision/);
    d.workflowRevision = 3;
    assert.throws(() => buildScheduleTarget(d, 'file'), /固定工作流 revision/);
    d.workflowSha = 'fakesha';
    assert.throws(() => buildScheduleTarget(d, null), /尚未验证/);
    assert.equal(buildScheduleTarget(d, 'file').type, 'workflow');
  });
  test('dedupe workflow mandates completed ScanJob and never sends runtime root IDs', () => {
    const d = createDefaultScheduleDraft();
    d.targetType = 'workflow'; d.workflowId = '4';
    d.workflowRevision = 2; d.workflowSha = 'pin';
    d.workflowRootIds = ['1', '2'];
    assert.throws(() => buildScheduleTarget(d, 'dedupe'), /已完成扫描/);
    d.workflowScanJobId = '12';
    assert.deepEqual(buildScheduleTarget(d, 'dedupe'), {
      type: 'workflow', workflow_id: 4, workflow_revision: 2,
      definition_sha256: 'pin', action: 'preview', runtime_inputs: { scan_job_id: 12 },
    });
  });
  test('file and organizer workflows can bind optional runtime root IDs', () => {
    const d = createDefaultScheduleDraft();
    d.targetType = 'workflow'; d.workflowId = '8';
    d.workflowRevision = 1; d.workflowSha = 'pin';
    for (const mode of ['file', 'organizer'] as const) {
      assert.equal((buildScheduleTarget(d, mode) as { runtime_inputs: unknown }).runtime_inputs, null);
      d.workflowRootIds = ['7', '11'];
      assert.deepEqual((buildScheduleTarget(d, mode) as { runtime_inputs: unknown }).runtime_inputs, {
        root_ids: [7, 11],
      });
      d.workflowRootIds = [];
    }
  });
  test('editor roundtrip preserves existing immutable pinned workflow revision and SHA', () => {
    const schedule = {
      id: 3, name: 'workflow nightly', description: '', enabled: true,
      cron_expression: '15 3 * * *', timezone: 'UTC',
      target_type: 'workflow', target: {
        type: 'workflow', workflow_id: 5,
        workflow_revision: 19, definition_sha256: 'sha-of-r19',
        action: 'preview', runtime_inputs: { root_ids: [2, 9] },
      },
    } as ScheduleItem;
    const d = draftFromSchedule(schedule);
    assert.equal(d.workflowRevision, 19);
    assert.equal(d.workflowSha, 'sha-of-r19');
    assert.equal(d.workflowId, '5');
    assert.deepEqual(d.workflowRootIds, ['2','9']);
    const target = buildScheduleTarget(d, 'file');
    assert.deepEqual(target, schedule.target);
  });
  test('native editor uses server version, optimistic concurrency revision and explicit error handling', () => {
    const e = editor();
    for(const token of [
      'workflowApi.getWorkflowRevision(target.workflow_id, target.workflow_revision)',
      'workflowApi.getWorkflow(Number(id))', 'detail.current_revision',
      'detail.definition_sha256', 'workflowEpoch.current === ticket',
      'previewEpoch.current === ticket', 'schedulerApi.previewRecurrence(cron, timezone, 5)',
      'schedulerApi.updateSchedule(schedule.id, { ...payload, expected_revision: schedule.revision })',
      'schedulerApi.createSchedule(payload)', 'await saveMutation.mutateAsync({ ...draft })',
      'createDefaultScheduleDraft(browserTimezone)', 'getStructuredApiError(err)',
      'onPointerDownOutside={event => event.preventDefault()}',
    ]) assert.ok(e.includes(token), token);
  });
  test('Scheduler list admin toggle uses expected revision and Run now explicit confirmation', () => {
    const p = page();
    for(const token of [
      "user?.role === 'admin'", '<ConsoleConfirmDialog open={runTarget !== null}',
      'if (!isAdmin || !runTarget || runInFlight.current || runMutation.isPending) return',
      'await runMutation.mutateAsync(runTarget)', 'schedule.revision',
      'expected_revision: schedule.revision', 'enableInFlight.current',
      "onChange={event => { void handleToggle(row, event.target.checked); }}",
      "schedulerApi.listSchedules(1, 200, true)",
      "refetchInterval: 15000", 'skip_if_active',
    ]) assert.ok(p.includes(token), token);
    assert.doesNotMatch(p, /from ['"]antd['"]|@ant-design\/icons|<Popconfirm\b|<Table\b|<Switch\b/);
  });
  test('Run now differentiates dispatched versus overlap skip and refetches both views', () => {
    const p = page();
    for (const token of [
      "run.status === 'dispatched'", "run.status === 'skipped_overlap'",
      '已有同计划任务仍在运行', 'run.error_text',
      "queryKey: ['schedules']", "queryKey: ['schedule-runs']",
    ]) assert.ok(p.includes(token), token);
  });
  test('native history preserves durable revision, Task link and failure details', () => {
    const h = history();
    for(const token of [
      "schedulerApi.listRuns(schedule!.id, 100)", 'refetchInterval: schedule ? 5000 : false',
      "['schedule-runs', schedule?.id]", 'run.schedule_revision',
      "navigate('/tasks?task=' + run.work_job_id)", 'run.error_code', 'run.error_text',
      '<ConsoleSheet', 'nfc-overlay-drawer',
    ]) {
      if(token === "['schedule-runs', schedule?.id]") {
        assert.ok(h.includes("['schedule-runs', schedule?.id]")); continue;
      }
      if(token === 'nfc-overlay-drawer') {
        assert.ok(read('src/components/ui/ConsoleSheet.tsx').includes(token)); continue;
      }
      assert.ok(h.includes(token), token);
    }
  });
  test('owned CSS drops AntD scheduler selectors and keeps 767px/mobile/dark/focus', () => {
    const css = read('src/styles/pages/scheduler.css');
    for(const token of [
      '.nfc-v2-scheduler-table', '.nfc-v2-scheduler-editor',
      '.nfc-v2-scheduler-history', '.nfc-scheduler-form-grid',
      '.nfc-scheduler-pin-panel', 'width:100vw',
      'grid-template-columns:1fr', "data-theme='dark'",
      'prefers-reduced-motion:reduce', 'focus-visible',
    ]) assert.ok(css.includes(token), token);
    assert.doesNotMatch(css, /\.ant-modal|\.ant-drawer|--ant-color/);
  });
});
