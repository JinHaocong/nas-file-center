import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  countFilterLeaves, createFilterNode, changeFilterField, changeFilterOperator,
  canAppendFilterChild, addFilterTag, formatFilterMtimeLocal, parseFilterMtimeLocal,
  DEFAULT_CHILD,
} from '../src/utils/workflowFilterActions';
import { MAX_FILTER_DEPTH, MAX_FILTER_LEAVES, MAX_FILTER_CHILDREN } from '../src/utils/filterMatrix';
import type { FilterLeafNode, FilterAndOrNode, FilterNode } from '../src/types/workflow';
const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const extension: FilterLeafNode = { field: 'extension', operator: 'eq', value: 'jpg', case_sensitive: false };

describe('Console v2 native Utility and Filter workflow controls', () => {
  test('AST constructors preserve old defaults and refuse deeper composites', () => {
    assert.deepEqual(createFilterNode('leaf', 0), { ...extension, value: 'txt' });
    assert.deepEqual(createFilterNode('and', 0), { op: 'and', children: [extension] });
    assert.deepEqual(createFilterNode('or', 0), { op: 'or', children: [extension] });
    assert.deepEqual(createFilterNode('not', 0), {
      op: 'not', child: { field: 'name', operator: 'startswith', value: '.', case_sensitive: false },
    });
    assert.equal(createFilterNode('and', MAX_FILTER_DEPTH), null);
    assert.equal(createFilterNode('not', MAX_FILTER_DEPTH), null);
    assert.notEqual(createFilterNode('leaf', MAX_FILTER_DEPTH), null);
  });
  test('matrix and operator changes preserve field values and scalar/list shape', () => {
    assert.deepEqual(changeFilterField(extension, 'size'), { ...extension, field: 'size', value: 0 });
    const tags = changeFilterOperator(extension, 'in');
    assert.deepEqual(tags.value, ['jpg']);
    assert.equal(changeFilterOperator(tags, 'nin').operator, 'nin');
    assert.equal(changeFilterOperator(tags, 'eq').value, 'jpg');
    assert.equal(changeFilterOperator(extension, 'contains'), extension);
    assert.deepEqual(changeFilterField(tags, 'media_type'), { ...tags, field: 'media_type', value: ['image'] });
    assert.equal(changeFilterField(extension, 'mtime').field, 'mtime');
  });
  test('tree leaf/child limits count nested AND, OR and NOT safely', () => {
    const tree: FilterNode = { op: 'and', children: [
      { op: 'not', child: extension }, { op: 'or', children: [extension, extension] },
    ] };
    assert.equal(countFilterLeaves(tree), 3);
    assert.equal(canAppendFilterChild(tree as FilterAndOrNode), true);
    const fullChildren: FilterAndOrNode = { op: 'and', children: Array.from({length:MAX_FILTER_CHILDREN}, () => ({...DEFAULT_CHILD})) };
    assert.equal(canAppendFilterChild(fullChildren), false);
    const fullLeaves: FilterAndOrNode = { op: 'or', children: [
      { op: 'and', children: Array.from({length:MAX_FILTER_LEAVES}, () => ({...extension})) },
    ] };
    assert.equal(countFilterLeaves(fullLeaves), MAX_FILTER_LEAVES);
    assert.equal(canAppendFilterChild(fullLeaves), false);
  });
  test('list values remain individual strings; extensions normalized without splitting commas', () => {
    const tags: FilterLeafNode = { ...extension, operator: 'in', value: ['jpg'] };
    const next = addFilterTag(tags, '.PNG ');
    assert.deepEqual(next.value, ['jpg', 'png']);
    assert.equal(addFilterTag(next, 'png'), next);
    assert.equal(addFilterTag(next, ' '), next);
    const names: FilterLeafNode = { field: 'name', operator: 'in', value: ['hello, world'] };
    assert.deepEqual(addFilterTag(names, 'another, item').value, ['hello, world','another, item']);
  });
  test('Filter mtime preserves old ISO instant while editing local time, rejects invalid', () => {
    const iso = new Date(2026, 8, 21, 15, 23, 18, 321).toISOString();
    const value = formatFilterMtimeLocal(iso);
    assert.equal(value, '2026-09-21T15:23:18.321');
    assert.equal(parseFilterMtimeLocal(value), iso);
    assert.equal(parseFilterMtimeLocal(''), '');
    assert.equal(formatFilterMtimeLocal('garbage'), '');
    for (const raw of ['2026-02-30T15:00','2026-13-01T15:00','2026-09-21T27:00','garbage']) {
      assert.equal(parseFilterMtimeLocal(raw), null);
    }
  });
  test('Utility remains managed-root only, warns on traversal, preserves unavailable saved root', () => {
    const s = read('src/components/workflows/SingleChildWrapperCollapseStepEditor.tsx');
    for (const token of [
      "queryKey: ['indexesRootsList']", 'indexesApi.listIndexes(1, 100)',
      'savedUnknownRoot', 'knownRootIds.includes(rootId)',
      'Number.isSafeInteger(rootId)', 'root_id: rootId',
      'if (readOnly', 'disabled={readOnly}', 'aria-invalid={invalidSubpath}',
      'aria-describedby=', 'role="alert"', 'Preview 只读发现候选',
      'nfc-workflow-field-spaced', 'nfc-workflow-full-control',
      "subpath.startsWith('/')", 'subpath: event.target.value',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Alert\b|<Select\b|<Input\b/);
  });
  test('Native FilterBuilder retains recursive AST, matrix, read-only and semantic controls', () => {
    const s = read('src/components/workflows/FilterBuilder.tsx');
    for (const token of [
      'nfc-filter-builder', 'nfc-filter-leaf-card', 'nfc-filter-group-card',
      'nfc-filter-not-card', 'FIELD_OPTIONS', 'OPERATOR_LABELS',
      'ALLOWED_OPERATORS_BY_FIELD', 'MEDIA_TYPE_OPTIONS', 'MAX_FILTER_DEPTH',
      'createFilterNode', 'changeFilterField', 'changeFilterOperator',
      'canAppendFilterChild', 'addFilterTag', 'parseFilterMtimeLocal',
      'normalizeExtension', 'FilterTags', '<NativeSelect',
      'onDelete', 'readOnly', 'case_sensitive',
      'nfc-filter-nested', 'children: [...group.children', 'value: next',
      'disabled={readOnly}', 'disabled={!canAddChild}',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Card\b|<InputNumber\b|<DatePicker\b|<Switch\b|<Select\b/);
    const wrapper = read('src/components/workflows/FilterStepEditor.tsx');
    assert.ok(wrapper.includes('if (!readOnly) onChange({ ...step, filter: newCond })'));
  });
  test('CSS includes dark mode, mobile tap targets, keyboard focus and reduced motion', () => {
    const css = read('src/styles/console-v2-workflow-filter-utility.css');
    const main = read('src/main.tsx');
    for (const token of [
      '.nfc-v2-filter-leaf-fields','.nfc-v2-filter-node','.nfc-v2-filter-tags',
      '.nfc-v2-filter-media-list','.nfc-v2-utility-editor',
      "[data-theme='dark']", ':focus-visible', '@media (max-width:767px)',
      'min-height:44px', '@media (prefers-reduced-motion:reduce)',
    ]) assert.ok(css.includes(token), token);
    assert.ok(main.includes("import './styles/console-v2-workflow-filter-utility.css';"));
  });
});
