import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Scheduler S4 API and responsive UI contract', () => {
  test('Scheduler is routed and visible in the Automation navigation group', () => {
    const router = read('src/router/index.tsx');
    const sidebar = read('src/components/Sidebar.tsx');

    assert.match(router, /path="schedules" element=\{<SchedulerPage \/>\}/);
    assert.match(sidebar, /key: '\/schedules'.*label: '计划任务'/);
    assert.match(sidebar, /groupLabel\('自动化'\)[\s\S]*leafMenuItems\[7\], leafMenuItems\[8\]/);
  });

  test('Scheduler API exposes authenticated ledger, admin mutations, run history and recurrence preview', () => {
    const api = read('src/api/scheduler.ts');

    assert.match(api, /api\.get<PaginatedResponse<ScheduleItem>>/);
    assert.match(api, /\/api\/schedules\/\$\{id\}\/runs/);
    assert.match(api, /api\.post<ScheduleItem>\('\/api\/schedules'/);
    assert.match(api, /api\.put<ScheduleItem>/);
    assert.match(api, /\/run-now/);
    assert.match(api, /\/api\/schedules\/recurrence\/preview/);
  });

  test('desktop and mobile surfaces include editor, run history, task linkage and admin-only actions', () => {
    const page = read('src/pages/Scheduler/index.tsx');

    assert.match(page, /ResponsiveDataView/);
    assert.match(page, /nfc-scheduler-mobile-card/);
    assert.match(page, /ScheduleEditorModal/);
    assert.match(page, /ScheduleHistoryDrawer/);
    assert.match(page, /user\?\.role === 'admin'/);
    assert.match(page, /Run now/);
    assert.match(page, /\/tasks\?task=\$\{run\.work_job_id\}/);
    assert.match(page, /workflow_revision/);
    assert.match(page, /definition_sha256/);
    assert.match(page, /不会自动 Freeze、Validate 或 Execute/);
  });

  test('mobile Scheduler layout stacks the editor and uses full-width run history', () => {
    const css = read('src/styles/pages/scheduler.css');

    assert.match(
      css,
      /@media \(max-width: 767px\)[\s\S]*\.nfc-scheduler-form-grid\s*\{[\s\S]*grid-template-columns:\s*1fr/
    );
    assert.match(
      css,
      /\.nfc-scheduler-history-drawer \.ant-drawer-content-wrapper\s*\{[\s\S]*width:\s*100vw !important/
    );
  });

  test('task center supports direct links from Scheduler history', () => {
    const tasks = read('src/pages/Tasks/index.tsx');

    assert.match(tasks, /useSearchParams/);
    assert.match(tasks, /searchParams\.get\('task'\)/);
    assert.match(tasks, /workflow-scheduled/);
  });
});
