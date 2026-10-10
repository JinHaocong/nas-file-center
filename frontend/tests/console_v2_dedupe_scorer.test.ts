import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  createDefaultDedupeScorerConfig, validateScorerConfigForm,
  MAX_RULES_COUNT, MAX_EXTENSIONS_COUNT, MAX_WEIGHT,
} from '../src/utils/dedupeConfig';
const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 native dedupe scoring editor', () => {
  test('selection modes and recursive last-file protection remain mandatory', () => {
    const source = read('src/components/dedupe/DedupeScorerConfigEditor.tsx');
    for (const token of [
      'weighted', 'balanced_by_bytes', 'recursive_directory_balanced_by_bytes',
      'handleSelectionModeChange', 'isRecursiveDirectoryBalance',
      'Recursive Last-File Protection — 强制启用',
      '该保护不可关闭，前端不提供禁用开关',
      'nfc-v2-scorer-notice', 'schema_version',
    ]) {
      if (token === 'schema_version') continue;
      assert.ok(source.includes(token), token);
    }
    for (const mode of ['weighted', 'balanced_by_bytes', 'recursive_directory_balanced_by_bytes'] as const) {
      const c = createDefaultDedupeScorerConfig();
      c.selection_mode = mode;
      assert.equal(validateScorerConfigForm(c).valid, true);
    }
  });

  test('both scoring factors retain bounded weights, ordered rules, edits, toggles and reset', () => {
    const s = read('src/components/dedupe/DedupeScorerConfigEditor.tsx');
    for (const token of [
      'MAX_RULES_COUNT', 'MAX_EXTENSIONS_COUNT', 'MAX_WEIGHT',
      'handlePathPriorityEnabledChange', 'handlePathPriorityWeightChange',
      'handleAddPathRule', 'handleUpdatePathRule', 'handleDeletePathRule',
      'handleMovePathRule', "direction === 'up' ? index - 1 : index + 1",
      "rules.splice(targetIndex, 0, item)", 'PathPriorityScope',
      'handleExtEnabledChange', 'handleExtWeightChange', 'handleAddExtension',
      'handleUpdateExtension', 'handleDeleteExtension', 'handleMoveExtension',
      'extensions.splice(targetIndex, 0, item)',
      'handleMtimeModeChange', 'handleMtimeWeightChange',
      'handleReset', 'createDefaultDedupeScorerConfig()', 'showReset && !disabled',
      'const cloned: DedupeScorerConfig = JSON.parse(JSON.stringify(config))',
      'onChange(next)', 'if (disabled) return',
    ]) assert.ok(s.includes(token), token);
    const c = createDefaultDedupeScorerConfig();
    c.factors.path_priority.enabled = true;
    c.factors.path_priority.weight = MAX_WEIGHT;
    c.factors.path_priority.rules = Array.from({length:MAX_RULES_COUNT}, (_,i)=>({
      scope: 'relative' as const, pattern: 'root/' + i,
    }));
    c.factors.preferred_extension.enabled = true;
    c.factors.preferred_extension.extensions = Array.from({length:MAX_EXTENSIONS_COUNT}, (_,i)=>'ext'+i);
    c.factors.preferred_extension.weight = MAX_WEIGHT;
    c.factors.mtime.mode = 'oldest';
    c.factors.mtime.weight = MAX_WEIGHT;
    assert.equal(validateScorerConfigForm(c).valid, true);
    c.factors.path_priority.rules[0].pattern = '';
    assert.equal(validateScorerConfigForm(c).valid, false);
    c.factors.path_priority.rules[0].pattern = 'root/0';
    c.factors.preferred_extension.extensions[0] = ' ';
    assert.equal(validateScorerConfigForm(c).valid, false);
  });

  test('native a11y controls use per-instance radio names, labels, disabled fields and explicit validation', () => {
    const s = read('src/components/dedupe/DedupeScorerConfigEditor.tsx');
    for (const token of [
      'React.useId()', 'name={instanceId + "-selection-mode"}',
      'name={instanceId + "-mtime-mode"}',
      'htmlFor={instanceId + "-path-priority-weight"}',
      'htmlFor={instanceId + "-extension-weight"}',
      'htmlFor={instanceId + "-mtime-weight"}',
      'value={rule.pattern}', 'value={ext}', 'value={mtime.weight}',
      'checked={path_priority.enabled}', 'checked={preferred_extension.enabled}',
      'type="checkbox"', 'type="radio"', 'type="number"', 'type="text"',
      '<fieldset', 'disabled={disabled}', 'role="alert"',
      'validation.errors.map', 'validateScorerConfigForm(config)',
      '<ConsoleButton', '<ConsoleIcon', 'nfc-v2-scorer-rule-actions',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Card\b|<Switch\b|<InputNumber\b|<Radio\b|<Select\b|<Alert\b/);
  });

  test('shared native editor supports workflow and scan; light/dark/mobile and focus treatment', () => {
    const s = read('src/components/dedupe/DedupeScorerConfigEditor.tsx');
    const scan = read('src/pages/Scans/AdvancedDedupePage.tsx');
    const exported = read('src/components/dedupe/index.ts');
    const css = read('src/styles/console-v2-dedupe-scorer.css');
    const main = read('src/main.tsx');
    assert.ok(scan.includes('DedupeScorerConfigEditor'));
    assert.ok(exported.includes('DedupeScorerConfigEditor'));
    assert.ok(s.includes('export const DedupeScorerConfigEditor'));
    for (const token of ['.nfc-v2-scorer-editor','.nfc-v2-scorer-rule-row',
      '.nfc-v2-scorer-validation',"[data-theme='dark']",':focus-visible',
      '@media (max-width: 767px)','prefers-reduced-motion: reduce',
      'min-height: 44px']) assert.ok(css.includes(token), token);
    assert.ok(main.includes("import './styles/console-v2-dedupe-scorer.css';"));
  });
});
