import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { canDeleteStep, canMoveStep } from '../src/utils/workflowTopology';
import type { WorkflowStep } from '../src/types/workflow';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 StepCard native UI and unchanged workflow definitions', () => {
  test('all 9 step kinds keep their exact editor delegation and previews', () => {
    const s = read('src/components/workflows/StepCard.tsx');
    for (const kind of [
      'scan', 'filter', 'rename', 'move', 'touch', 'quarantine', 'organize',
      'dedupe', 'single_child_wrapper_collapse',
    ]) {
      assert.ok(s.includes("case '" + kind + "':"), kind + ' metadata');
      assert.ok(s.includes("step.type === '" + kind + "'"), kind + ' editor');
    }
    for (const editor of [
      'ScanStepEditor', 'FilterStepEditor', 'RenameStepEditor', 'MoveStepEditor',
      'TouchStepEditor', 'QuarantineStepEditor', 'OrganizerStepEditor',
      'DedupeStepEditor', 'SingleChildWrapperCollapseStepEditor',
    ]) assert.ok(s.includes('<' + editor), editor);
    for (const token of [
      'step.root_ids.join', 'step.destination_root_id', 'step.touch_now',
      'step.mtime_ns / 1e6', 'step.profile_snapshot?.name', 'step.scorer_config?.selection_mode',
      'getStepMeta(step)', 'mode={mode}', 'readOnly={readOnly}',
    ]) assert.ok(s.includes(token), token);
  });

  test('semantic disclosure, focusable controls and readOnly guard apply at action boundaries', () => {
    const s = read('src/components/workflows/StepCard.tsx');
    for (const token of [
      '<section', '<header', '<button type="button"', 'aria-expanded={expanded}',
      'aria-controls={editorId}', 'const editorId = useId()',
      'hidden={!expanded}', 'onClick={() => setExpanded(value => !value)}',
      'ConsoleButton', '<ConsoleIcon',
      'if (!readOnly && canMoveUp) onMoveUp()',
      'if (!readOnly && canMoveDown) onMoveDown()',
      'if (!readOnly && canDelete) onDelete()',
      'if (!readOnly && updated.type === step.type && updated.id === step.id) onChange(updated)',
      'disabled={!canMoveUp}', 'disabled={!canMoveDown}', 'disabled={!canDelete}',
      '!readOnly && (', '只读',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Card\b|<Tag\b|<Tooltip\b|<Button\b/);
    const scan: WorkflowStep = { id: 's', type: 'scan', root_ids: [1] };
    const rename: WorkflowStep = { id: 'r', type: 'rename', pattern: 'before', replacement: 'after' };
    assert.equal(canMoveStep([scan, rename], 1, 'up', 'file'), false);
    assert.equal(canDeleteStep([scan, rename], 0, 'file'), false);
  });

  test('rename editor preserves raw literal replacement incl empty string and read-only guard', () => {
    const s = read('src/components/workflows/RenameStepEditor.tsx');
    for (const token of [
      'type="text"', 'required', 'value={step.pattern}', 'value={step.replacement}',
      'pattern: event.target.value', 'replacement: event.target.value',
      'fieldset', 'disabled={readOnly}', 'if (!readOnly)',
      'htmlFor=', 'aria-describedby=', '不支持正则表达式', '不支持正则捕获组',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|<Form\b|<Input\b/);
  });

  test('quarantine reason remains required, exact string, audit-visible and immutable when readOnly', () => {
    const s = read('src/components/workflows/QuarantineStepEditor.tsx');
    for (const token of [
      'value={step.reason}', 'reason: event.target.value', 'disabled={readOnly}',
      'if (!readOnly)', 'required', 'aria-describedby=', '审计日志',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|<Form\b|<Input\b/);
  });

  test('dedupe reuses established scoring config/defaults without introducing a new authority path', () => {
    const s = read('src/components/workflows/DedupeStepEditor.tsx');
    for (const token of [
      'createDefaultDedupeScorerConfig()', '<DedupeScorerConfigEditor',
      'onChange={handleConfigChange}', 'disabled={readOnly}',
      'if (readOnly) return', 'scorer_config: newConfig', 'compile_digest',
      '单一步骤拓扑', 'role="note"', '<ConsoleIcon',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Alert\b/);
  });

  test('CSS includes scoped dark/mobile, accessible focus and reduced-motion treatments', () => {
    const css = read('src/styles/console-v2-workflow-step-card.css');
    const main = read('src/main.tsx');
    for (const token of [
      '.nfc-v2-step-card', '.nfc-v2-step-toggle', '.nfc-v2-step-type',
      '.nfc-v2-step-actions', '.nfc-v2-simple-step-form',
      '.nfc-v2-step-field', '.nfc-v2-step-notice',
      '[data-theme=\'dark\']', ':focus-visible',
      '@media (max-width: 767px)', 'min-height: 44px',
      '@media (prefers-reduced-motion: reduce)',
    ]) assert.ok(css.includes(token), token);
    assert.ok(main.includes("import './styles/console-v2-workflow-step-card.css';"));
  });
});
