import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { canDeleteStep, canMoveStep, getAllowedInsertions } from '../src/utils/workflowTopology';
import type { WorkflowStep } from '../src/types/workflow';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const scan: WorkflowStep = { id: 'scan', type: 'scan', root_ids: [1] };
const filter: WorkflowStep = {
  id: 'filter', type: 'filter',
  filter: { field: 'extension', operator: 'eq', value: 'jpg', case_sensitive: false },
};
const rename: WorkflowStep = { id: 'rename', type: 'rename', pattern: 'draft', replacement: 'final' };
const quarantine: WorkflowStep = { id: 'quarantine', type: 'quarantine', reason: 'quarantine by workflow' };

describe('Console v2 StepList native add menu and topology safety', () => {
  test('allowed append types cannot bypass file, organizer, dedupe or utility topology', () => {
    assert.deepEqual(getAllowedInsertions([scan], 'file'), ['filter', 'rename', 'move', 'touch', 'quarantine']);
    assert.deepEqual(getAllowedInsertions([scan, filter, rename], 'file'), ['rename', 'move', 'touch', 'quarantine']);
    assert.deepEqual(getAllowedInsertions([scan, quarantine], 'file'), []);
    assert.deepEqual(getAllowedInsertions([scan], 'organizer'), []);
    assert.deepEqual(getAllowedInsertions([scan], 'dedupe'), []);
    assert.deepEqual(getAllowedInsertions([scan], 'utility'), []);
    assert.equal(canMoveStep([scan, filter, rename], 1, 'up', 'file'), false);
    assert.equal(canMoveStep([scan, filter, rename], 2, 'up', 'file'), false);
    assert.equal(canDeleteStep([scan, filter, rename], 0, 'file'), false);
    assert.equal(canDeleteStep([scan, quarantine], 1, 'file'), true);
    assert.equal(canDeleteStep([scan, filter], 1, 'organizer'), false);
  });

  test('preserves all step constructors with exact defaults and readonly action guards', () => {
    const s = read('src/components/workflows/StepList.tsx');
    for (const token of [
      "case 'scan':", "case 'filter':", "case 'rename':",
      "case 'move':", "case 'touch':", "case 'quarantine':",
      "case 'organize':", "case 'dedupe':", "case 'single_child_wrapper_collapse':",
      "operator: 'eq', value: 'jpg', case_sensitive: false",
      "pattern: 'draft', replacement: 'final'",
      "destination_root_id: 1, destination_subpath: ''",
      "touch_now: true, mtime_ns: null",
      "reason: 'quarantine by workflow'",
      "createDefaultOrganizerSnapshot('默认整理快照')",
      "createDefaultDedupeScorerConfig()",
      "root_id: 0, subpath: ''",
      "onChange([...steps, newStep])", "if (readOnly || !getAllowedInsertions(steps, mode).includes(type)) return",
      "if (readOnly || !canMoveStep(steps, index, direction, mode)) return",
      "if (readOnly || !canDeleteStep(steps, index, mode)) return",
      "if (readOnly || index < 0 || index >= steps.length) return",
      "canMoveUp={canMoveStep(", "canMoveDown={canMoveStep(",
      "canDelete={canDeleteStep(", "readOnly={readOnly}",
      "mode !== 'dedupe' && mode !== 'utility'",
    ]) assert.ok(s.includes(token), token);
  });

  test('native semantic dropdown handles trigger, menu keyboard, Escape, Tab and outside click', () => {
    const s = read('src/components/workflows/StepList.tsx');
    for (const token of [
      '<ConsoleButton', '<ConsoleIcon', 'nfc-v2-step-menu',
      'aria-haspopup="menu"', 'aria-expanded={menuOpen}',
      'aria-controls=', 'role="menu"', 'role="menuitem"',
      'disabled={!allowedInsertions.includes(item.key)}',
      'disabled={!canOpenMenu}', 'menuRef.current?.querySelectorAll',
      "event.key === 'Escape'", 'onBlur={(event) => {', 'event.relatedTarget',
      "'ArrowDown', 'ArrowUp', 'Home', 'End'",
      "document.addEventListener('pointerdown', handleOutside)",
      "document.removeEventListener('pointerdown', handleOutside)",
      'triggerRef.current?.focus()', 'setMenuOpen(false)', 'current === -1',
      'role="status"', '暂无工作流步骤，请从下方添加执行步骤',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Dropdown\b|<Empty\b|<Button\b/);
  });

  test('StepCard editors remain delegated and new CSS covers light, dark, focus and mobile', () => {
    const s = read('src/components/workflows/StepList.tsx');
    const builder = read('src/pages/Workflows/WorkflowBuilder.tsx');
    const css = read('src/styles/console-v2-workflow-builder.css');
    for (const token of ['<StepCard', 'onMoveUp=', 'onMoveDown=', 'onDelete=', 'onChange=']) {
      assert.ok(s.includes(token), token);
    }
    assert.ok(builder.includes('<StepList'));
    assert.ok(builder.includes('onChange={handleStepChange}'));
    for (const token of [
      '.nfc-v2-step-menu', '.nfc-v2-step-empty', ':focus-visible',
      "[data-theme='dark']", '@media (max-width: 767px)',
      'min-height: 44px', '@media (prefers-reduced-motion: reduce)',
    ]) assert.ok(css.includes(token), token);
  });
});
