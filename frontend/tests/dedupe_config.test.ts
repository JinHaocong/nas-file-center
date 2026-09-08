import test, { describe } from 'node:test';
import assert from 'node:assert';
import {
  createDefaultDedupeScorerConfig,
  validateScorerConfigForm,
  isScorerConfigDirty,
  buildDirectAdvancedGeneratePayload,
  buildWorkflowGeneratePayload,
} from '../src/utils/dedupeConfig';
import { DedupeScorerConfig } from '../src/types/dedupe';

describe('Gate5-D / D4 Dedupe Scorer Configuration & Payload Primitives', () => {
  describe('Default Config Factory', () => {
    test('createDefaultDedupeScorerConfig creates complete V1 shape', () => {
      const cfg = createDefaultDedupeScorerConfig();
      assert.strictEqual(cfg.schema_version, 1);
      assert.strictEqual(cfg.selection_mode, 'weighted');
      assert.deepStrictEqual(cfg.factors, {
        path_priority: {
          enabled: false,
          weight: 0,
          rules: [],
        },
        preferred_extension: {
          enabled: false,
          weight: 0,
          extensions: [],
        },
        mtime: {
          mode: 'none',
          weight: 0,
        },
      });
    });
  });

  describe('Form Validation Limits', () => {
    test('default config passes validation', () => {
      const cfg = createDefaultDedupeScorerConfig();
      const res = validateScorerConfigForm(cfg);
      assert.strictEqual(res.valid, true);
      assert.strictEqual(res.errors.length, 0);
    });

    test('rejects weight outside 0..10000 or non-integer', () => {
      const cfg = createDefaultDedupeScorerConfig();
      cfg.factors.path_priority.weight = -1;
      let res = validateScorerConfigForm(cfg);
      assert.strictEqual(res.valid, false);

      cfg.factors.path_priority.weight = 10001;
      res = validateScorerConfigForm(cfg);
      assert.strictEqual(res.valid, false);

      cfg.factors.path_priority.weight = 1.5;
      res = validateScorerConfigForm(cfg);
      assert.strictEqual(res.valid, false);
    });

    test('rejects rules exceeding 64 items or pattern > 512 chars', () => {
      const cfg = createDefaultDedupeScorerConfig();
      cfg.factors.path_priority.rules = Array.from({ length: 65 }, (_, i) => ({
        scope: 'absolute' as const,
        pattern: `/path/${i}`,
      }));
      let res = validateScorerConfigForm(cfg);
      assert.strictEqual(res.valid, false);

      cfg.factors.path_priority.rules = [
        { scope: 'absolute', pattern: 'a'.repeat(513) },
      ];
      res = validateScorerConfigForm(cfg);
      assert.strictEqual(res.valid, false);

      cfg.factors.path_priority.rules = [
        { scope: 'absolute', pattern: '   ' },
      ];
      res = validateScorerConfigForm(cfg);
      assert.strictEqual(res.valid, false);
    });

    test('rejects extensions exceeding 64 items or extension > 64 chars', () => {
      const cfg = createDefaultDedupeScorerConfig();
      cfg.factors.preferred_extension.extensions = Array.from({ length: 65 }, (_, i) => `ext${i}`);
      let res = validateScorerConfigForm(cfg);
      assert.strictEqual(res.valid, false);

      cfg.factors.preferred_extension.extensions = ['a'.repeat(65)];
      res = validateScorerConfigForm(cfg);
      assert.strictEqual(res.valid, false);

      cfg.factors.preferred_extension.extensions = [''];
      res = validateScorerConfigForm(cfg);
      assert.strictEqual(res.valid, false);
    });

    test('rejects invalid selection_mode or mtime mode', () => {
      const cfg = createDefaultDedupeScorerConfig() as any;
      cfg.selection_mode = 'invalid_mode';
      let res = validateScorerConfigForm(cfg);
      assert.strictEqual(res.valid, false);

      const cfg2 = createDefaultDedupeScorerConfig() as any;
      cfg2.factors.mtime.mode = 'bogus';
      res = validateScorerConfigForm(cfg2);
      assert.strictEqual(res.valid, false);
    });
  });

  describe('Dirty Detection', () => {
    test('detects differences in selection_mode, factors, rules, extensions', () => {
      const c1 = createDefaultDedupeScorerConfig();
      const c2 = createDefaultDedupeScorerConfig();
      assert.strictEqual(isScorerConfigDirty(c1, c2), false);

      c2.selection_mode = 'balanced_by_bytes';
      assert.strictEqual(isScorerConfigDirty(c1, c2), true);

      const c3 = createDefaultDedupeScorerConfig();
      c3.factors.path_priority.enabled = true;
      assert.strictEqual(isScorerConfigDirty(c1, c3), true);

      const c4 = createDefaultDedupeScorerConfig();
      c4.factors.preferred_extension.extensions = ['jpg'];
      assert.strictEqual(isScorerConfigDirty(c1, c4), true);

      const c5 = createDefaultDedupeScorerConfig();
      c5.factors.mtime.mode = 'newest';
      assert.strictEqual(isScorerConfigDirty(c1, c5), true);
    });
  });

  describe('Generate Payload Builders & Authority Separation', () => {
    test('buildDirectAdvancedGeneratePayload uses expected_preview_digest and NO legacy fields', () => {
      const cfg = createDefaultDedupeScorerConfig();
      const digest = 'a'.repeat(64);
      const payload = buildDirectAdvancedGeneratePayload(cfg, digest);

      assert.strictEqual(payload.expected_preview_digest, digest);
      assert.deepStrictEqual(payload.scorer_config, cfg);
      assert.strictEqual('policy' in payload, false);
      assert.strictEqual('path_priority_patterns' in payload, false);
      assert.strictEqual('relative_path_priority_patterns' in payload, false);
    });

    test('buildWorkflowGeneratePayload uses expected_compile_digest', () => {
      const compileDigest = 'c'.repeat(64);
      const payload = buildWorkflowGeneratePayload(compileDigest, 42);

      assert.strictEqual(payload.expected_compile_digest, compileDigest);
      assert.deepStrictEqual(payload.runtime_inputs, { scan_job_id: 42 });
      assert.strictEqual('expected_preview_digest' in payload, false);
      assert.strictEqual('root_ids' in payload.runtime_inputs, false);
    });
  });
});
