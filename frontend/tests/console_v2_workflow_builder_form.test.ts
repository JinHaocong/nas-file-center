import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { validateWorkflowBasicFields, canConfirmWorkflowModeReset } from '../src/utils/workflowBuilderActions';
const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 workflow native form', () => {
  test('name required and both fields trimmed before API submission', () => {
    assert.deepEqual(validateWorkflowBasicFields('   ', ' x '),
      {name: '', description: 'x', nameError: '请输入工作流名称'});
    assert.equal(validateWorkflowBasicFields('', '').nameError, '请输入工作流名称');
    assert.deepEqual(validateWorkflowBasicFields('  相册整理  ', '  仅预览  '),
      {name: '相册整理', description: '仅预览', nameError: ''});
    assert.equal(validateWorkflowBasicFields('X', '').description, '');
  });

  test('hydration, dirty detection, inline errors and revision authority', () => {
    const s = read('src/pages/Workflows/WorkflowBuilder.tsx');
    for (const term of [
      "setName(workflow.name ?? '')", "setDescription(workflow.description ?? '')",
      "setName('')", "setDescription('')", "setNameError('')",
      'setIsDirty(true)', 'setIsDirty(false)', 'nameInputRef.current?.focus()',
      'validateWorkflowBasicFields(name, description)', 'handleSave', '<form',
      'noValidate', 'onSubmit=', 'type="text"', '<textarea', 'required',
      'aria-invalid={Boolean(nameError)}', 'role="alert"', 'disabled={!canEdit}',
      'expected_current_revision: workflow.current_revision', 'schema_version: 1',
      'onClick={handleSave}', 'parseWorkflowRevisionQuery',
    ]) assert.ok(s.includes(term), term);
    assert.doesNotMatch(s, /from ['"]antd['"]|<Form\b|<Form\.Item\b|<Input\b|<Radio\b|Form\.useForm\(/);
  });

  test('four accessible modes and guarded topology confirmation', () => {
    const s = read('src/pages/Workflows/WorkflowBuilder.tsx');
    for (const term of [
      "'file', 'organizer', 'dedupe', 'utility'", '<fieldset', '<legend>',
      'aria-describedby=', 'type="radio"', 'name={formId',
      'checked={mode === option}', 'disabled={!canSwitchMode}',
      'handleModeChange(option)', "setConfirmation({ kind: 'mode'",
      'canConfirmWorkflowModeReset(', 'setSteps(defaultStepsForMode(confirmation.targetMode))',
      'createDefaultOrganizerSnapshot', 'createDefaultDedupeScorerConfig',
    ]) assert.ok(s.includes(term), term);
    assert.equal(canConfirmWorkflowModeReset(true, true, 'file', 'dedupe'), false);
    assert.equal(canConfirmWorkflowModeReset(false, false, 'file', 'dedupe'), false);
  });

  test('light/dark, focus, mobile and reduced-motion CSS', () => {
    const css = read('src/styles/console-v2-workflow-builder.css');
    for (const term of [
      '.nfc-v2-workflow-form', '.nfc-v2-workflow-field',
      '.nfc-v2-workflow-mode-choice', ':focus-visible', ':focus-within',
      "[data-theme='dark']", '@media (max-width: 767px)',
      'min-height: 44px', '@media (prefers-reduced-motion: reduce)',
    ]) assert.ok(css.includes(term), term);
  });
});
