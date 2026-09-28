import test, { describe } from 'node:test';
import assert from 'node:assert';
import { readApiErrorResponse } from '../src/api/client';

describe('API error response body handling', () => {
  test('parses JSON error from a single body read', async () => {
    const response = new Response(
      JSON.stringify({ detail: 'PLAN_STALE: source changed' }),
      { status: 409, headers: { 'Content-Type': 'application/json' } },
    );

    const error = await readApiErrorResponse(response);

    assert.strictEqual(error.status, 409);
    assert.strictEqual(error.message, 'PLAN_STALE: source changed');
    assert.deepStrictEqual(error.detail, { detail: 'PLAN_STALE: source changed' });
    assert.strictEqual(response.bodyUsed, true);
  });

  test('preserves plain-text backend errors without a second body read', async () => {
    const response = new Response('upstream proxy rejected freeze request', {
      status: 502,
      headers: { 'Content-Type': 'text/plain' },
    });

    const error = await readApiErrorResponse(response);

    assert.strictEqual(error.status, 502);
    assert.strictEqual(error.message, 'upstream proxy rejected freeze request');
    assert.deepStrictEqual(error.detail, {
      detail: 'upstream proxy rejected freeze request',
    });
  });

  test('uses HTTP status fallback for an empty error body', async () => {
    const response = new Response(null, { status: 500 });

    const error = await readApiErrorResponse(response);

    assert.strictEqual(error.status, 500);
    assert.strictEqual(error.message, '请求失败 (500)');
    assert.deepStrictEqual(error.detail, {});
  });

  test('extracts structured nested API messages', async () => {
    const response = new Response(
      JSON.stringify({
        detail: {
          error: {
            code: 'PLAN_FREEZE_BLOCKED',
            message: '计划项已发生变化，禁止冻结',
          },
        },
      }),
      { status: 409, headers: { 'Content-Type': 'application/json' } },
    );

    const error = await readApiErrorResponse(response);

    assert.strictEqual(error.message, '计划项已发生变化，禁止冻结');
    assert.strictEqual(error.detail.detail.error.code, 'PLAN_FREEZE_BLOCKED');
  });
});
