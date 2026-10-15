import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const view = read('src/pages/ArchiveRecovery/index.tsx');

describe('Stage 5E-AH — Archive Recovery WorkJob continuity', () => {
  test('task identity is URL-bound, validated and refreshed without passwords in URL', () => {
    assert.ok(view.includes('useSearchParams()'));
    assert.ok(view.includes("searchParams.get('task')"));
    assert.ok(view.includes('/^[1-9][0-9]*$/.test(rawTaskId)'));
    assert.ok(view.includes('Number.isSafeInteger(parsedTaskId)'));
    assert.ok(view.includes("next.set('task', String(data.work_job_id))"));
    assert.ok(view.includes("setPassword('');"));
    assert.doesNotMatch(view, /setTaskId\(/, 'selection must not erase a WorkJob');
    assert.doesNotMatch(view, /next\.set\('password'/, 'never store secrets in a URL');
    assert.ok(view.includes("queryKey: ['archive-recovery-task', taskId]"));
    assert.ok(view.includes("queryKey: ['archive-recovery-report', taskId]"));
  });

  test('selection, manual path and folder changes do not detach active task evidence', () => {
    assert.match(view, /onClick=\{\(\) => \{\s*setSelected\(entry\.path\);\s*setPassword\(''\);\s*check\.reset\(\);\s*start\.reset\(\);/);
    assert.match(view, /onChange=\{event => \{\s*setSelected\(event\.target\.value\);\s*setPassword\(''\);\s*check\.reset\(\);\s*start\.reset\(\);/);
    assert.match(view, /if \(next === folder\) return;[\s\S]*?setFolder\(next\);[\s\S]*?setSelected\(''\);[\s\S]*?check\.reset\(\);/);
    const beforeFinish = view.split('const startAnotherRecovery')[0];
    assert.doesNotMatch(beforeFinish, /next\.delete\('task'\)/);
    assert.ok(view.includes('Boolean(taskId)}'));
    assert.ok(view.includes('disabled={!checkedSourceMatchesSelected'));
  });

  test('only explicit terminal acknowledgement allows another recovery', () => {
    assert.ok(view.includes("const recoveryJobMatches = job.data?.job_type === 'archive-recovery'"));
    assert.ok(view.includes("const terminal = recoveryJobMatches &&"));
    assert.ok(view.includes("disabled={!recoveryJobMatches || !['running', 'queued'].includes"));
    assert.ok(view.includes("job.data && !recoveryJobMatches"));
    assert.ok(view.includes("['completed', 'failed', 'cancelled'].includes"));
    assert.match(view, /const startAnotherRecovery = \(\) => \{\s*if \(!terminal \|\| taskId === null\) return;/);
    assert.match(view, /next\.delete\('task'\);[\s\S]*?setSelected\(''\);[\s\S]*?setPassword\(''\);/);
    assert.match(view, /\{terminal && <ConsoleButton onClick=\{startAnotherRecovery\}>开始下一次恢复<\/ConsoleButton>\}/);
    assert.equal((view.match(/next\.delete\('task'\)/g) || []).length, 1);
    assert.ok(view.includes('任务记录仍保留在任务中心'));
    assert.ok(view.includes('navigate(\'/tasks?task=\' + taskId)'));
    assert.ok(view.includes('tasksApi.cancelTask(taskId!)'));
    assert.ok(view.includes('role="alert">任务状态读取失败'));
  });

  test('real Chromium uses synthetic GET-only task details and no writes', () => {
    const browser = read('scripts/browser-archive-recovery-task-continuity.mjs');
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    assert.ok(browser.includes("BASE + '/archive-recovery?task=777'"));
    assert.ok(browser.includes("request.method() !== 'GET'"));
    assert.ok(browser.includes('blockedWrites'));
    assert.ok(browser.includes('outbound'));
    assert.ok(browser.includes("name: '开始下一次恢复'"));
    assert.ok(browser.includes('page.reload('));
    assert.ok(workflow.includes('node scripts/browser-archive-recovery-task-continuity.mjs'));
  });
  test('Stage 5E-AI selection and WorkJob matrices cover eight widths and shared GET-only fixtures', () => {
    const screens = [
      read('scripts/browser-archive-recovery-selection.mjs'),
      read('scripts/browser-archive-recovery-task-continuity.mjs'),
    ];
    const fixtures = read('scripts/visual-fixtures.mjs');
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    assert.ok(fixtures.includes('export function visualArchiveDirectoryFixture'));
    assert.ok(fixtures.includes('export const visualViewports'));
    assert.ok(fixtures.includes('export const visualThemes'));
    for (const script of screens) {
      assert.ok(script.includes('visualArchiveDirectoryFixture('));
      assert.ok(script.includes('for (const width of visualViewports)'));
      assert.ok(script.includes('for (const theme of visualThemes)'));
      assert.ok(script.includes('colorScheme: theme.system'));
      assert.ok(script.includes("localStorage.setItem('nfc_theme_mode', mode)"));
      assert.ok(script.includes('assert.equal(passed, 32)'));
      assert.ok(script.includes("request.method() !== 'GET'"));
      assert.ok(script.includes('outbound'));
      assert.ok(script.includes('blockedWrites'));
    }
    assert.ok(workflow.includes('node scripts/browser-archive-recovery-selection.mjs'));
    assert.ok(workflow.includes('node scripts/browser-archive-recovery-task-continuity.mjs'));
    assert.ok(workflow.includes('frontend/artifacts/browser-archive-recovery-selection/*.png'));
    assert.ok(workflow.includes('frontend/artifacts/browser-archive-recovery-task-continuity/*.png'));
    assert.ok(read('scripts/run-tests.mjs').includes('node --test scripts/visual-fixtures-archive.test.mjs'));
  });

});
