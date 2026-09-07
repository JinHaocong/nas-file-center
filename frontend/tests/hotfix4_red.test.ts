import { test, describe } from 'node:test';
import assert from 'node:assert';
import {
  parseWorkflowRevisionQuery,
  computePreviewRowIndex,
  createInitialScanStep,
} from '../src/utils/workflowRevisionParser';

describe('Gate5-C Hotfix4 P2-16: Strict Historical Revision Parser', () => {
  test('null, undefined or empty string returns valid current view', () => {
    assert.deepStrictEqual(parseWorkflowRevisionQuery(null), {
      isValid: true,
      isHistorical: false,
      revision: null,
    });
    assert.deepStrictEqual(parseWorkflowRevisionQuery(undefined), {
      isValid: true,
      isHistorical: false,
      revision: null,
    });
    assert.deepStrictEqual(parseWorkflowRevisionQuery(''), {
      isValid: true,
      isHistorical: false,
      revision: null,
    });
    assert.deepStrictEqual(parseWorkflowRevisionQuery('   '), {
      isValid: true,
      isHistorical: false,
      revision: null,
    });
  });

  test('non-numeric strings fail closed without fallback', () => {
    const invalidInputs = [
      'abc',
      'NaN',
      'undefined',
      'null',
      '1abc',
      'abc1',
      '1.5',
      '2.0',
      '0',
      '-1',
      '-100',
      '01',
      '1\n',
      '1\r',
      '1 ',
      ' 1',
      '1e5',
      'Infinity',
      '-Infinity',
      '999999999999999999999999999999',
    ];

    for (const raw of invalidInputs) {
      const res = parseWorkflowRevisionQuery(raw, 2);
      assert.strictEqual(res.isValid, false, `Expected isValid=false for input "${raw}"`);
      assert.strictEqual(res.isHistorical, false);
      assert.strictEqual(res.revision, null);
      assert.ok(res.errorMessage, `Expected error message for input "${raw}"`);
      assert.ok(res.errorMessage.includes('无效的历史版本号'));
    }
  });

  test('valid revision equal to current_revision is normalized to current view', () => {
    const res = parseWorkflowRevisionQuery('3', 3);
    assert.deepStrictEqual(res, {
      isValid: true,
      isHistorical: false,
      revision: 3,
    });
  });

  test('valid revision different from current_revision is marked historical', () => {
    const res = parseWorkflowRevisionQuery('2', 5);
    assert.deepStrictEqual(res, {
      isValid: true,
      isHistorical: true,
      revision: 2,
    });
  });

  test('valid revision without known current_revision is marked historical', () => {
    const res = parseWorkflowRevisionQuery('1', undefined);
    assert.deepStrictEqual(res, {
      isValid: true,
      isHistorical: true,
      revision: 1,
    });
  });
});

describe('Gate5-C Hotfix4 P2-17: Preview Pagination Snapshot & Row Index', () => {
  test('computePreviewRowIndex correctly calculates 1-based sequential index', () => {
    // Page 1, PageSize 50, item 0 -> 1
    assert.strictEqual(computePreviewRowIndex(1, 50, 0), 1);
    // Page 1, PageSize 50, item 49 -> 50
    assert.strictEqual(computePreviewRowIndex(1, 50, 49), 50);

    // Page 2, PageSize 50, item 0 -> 51
    assert.strictEqual(computePreviewRowIndex(2, 50, 0), 51);

    // Page 1, PageSize 100, item 99 -> 100
    assert.strictEqual(computePreviewRowIndex(1, 100, 99), 100);

    // Page 3, PageSize 20, item 5 -> 46
    assert.strictEqual(computePreviewRowIndex(3, 20, 5), 46);
  });
});

describe('Gate5-C Hotfix4: Initial Scan Step Root IDs Skeleton', () => {
  test('createInitialScanStep initializes with empty root_ids instead of hardcoded [1]', () => {
    const step = createInitialScanStep('step_scan_1');
    assert.strictEqual(step.id, 'step_scan_1');
    assert.strictEqual(step.type, 'scan');
    assert.deepStrictEqual(step.root_ids, []);
  });
});
