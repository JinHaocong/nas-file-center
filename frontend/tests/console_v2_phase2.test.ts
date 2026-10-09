import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { getPaginationState } from '../src/components/ui/paginationModel';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('console v2 phase 2: native Plan ledger', () => {
  test('empty, bounded and final-page pagination', () => {
    assert.deepEqual(getPaginationState(1, 20, 0), { pages: 1, current: 1, start: 0, end: 0 });
    assert.deepEqual(getPaginationState(3, 20, 43), { pages: 3, current: 3, start: 41, end: 43 });
    assert.deepEqual(getPaginationState(9, 20, 43), { pages: 3, current: 3, start: 41, end: 43 });
    assert.deepEqual(getPaginationState(-5, 20, 43), { pages: 3, current: 1, start: 1, end: 20 });
    assert.deepEqual(getPaginationState(2, 0, 43), { pages: 3, current: 2, start: 21, end: 40 });
  });

  test('new primitives are accessible and free of Ant Design imports', () => {
    for (const file of ['ConsoleButton.tsx', 'ConsoleEmpty.tsx', 'ConsolePagination.tsx']) {
      const source = read('src/components/ui/' + file);
      assert.doesNotMatch(source, /from ['"](?:antd|@ant-design\/icons)['"]/);
    }
    const buttons = read('src/components/ui/ConsoleButton.tsx');
    assert.match(buttons, /disabled=\{disabled \|\| loading\}/);
    assert.match(buttons, /aria-busy=/);
    const pagination = read('src/components/ui/ConsolePagination.tsx');
    assert.match(pagination, /aria-label="上一页"/);
    assert.match(pagination, /aria-label="下一页"/);
    assert.match(pagination, /getPaginationState/);
  });

  test('Plans list no longer renders Ant tables and paginators', () => {
    const page = read('src/pages/Plans/index.tsx');
    assert.match(page, /<table className="nfc-v2-plan-table">/);
    assert.match(page, /<ConsolePagination/);
    assert.match(page, /<ConsoleEmpty/);
    assert.match(page, /<ConsoleButton/);
    assert.doesNotMatch(page, /<Table\b|<Pagination\b|<Empty\b|from ['"]@ant-design\/icons['"]/);
  });

  test('Plans safety and lifecycle are preserved', () => {
    const page = read('src/pages/Plans/index.tsx');
    for (const token of [
      'PlanDeleteButton', 'PlanHistoryCleanupModal', 'LegacyPlanCleanup',
      'invalidatePlanDeleteFailure', 'deletePlanMutation',
      'queryClient.invalidateQueries', 'ResponsiveDataView', 'StatusBadge',
      'return hasActive ? 3000 : false', 'nfc-plan-mobile-card',
    ]) assert.ok(page.includes(token), token);
    assert.doesNotMatch(page, /(?:freezeMutation|executeMutation|allow_mutation)\s*=/);
  });

  test('the new visual ownership layer loads last and is responsive', () => {
    const main = read('src/main.tsx');
    const p1 = main.indexOf("import './styles/console-v2.css';");
    const p2 = main.indexOf("import './styles/console-v2-phase2.css';");
    assert.ok(p2 > p1 && p1 > 0);
    const css = read('src/styles/console-v2-phase2.css');
    assert.match(css, /\.nfc-v2-shell \.nfc-console-button/);
    assert.match(css, /\.nfc-v2-shell \.nfc-v2-plan-table/);
    assert.match(css, /@media \(max-width: 767px\)/);
    assert.match(css, /prefers-reduced-motion: reduce/);
  });
});
