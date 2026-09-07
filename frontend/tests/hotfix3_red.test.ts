import { describe, it } from 'node:test';
import assert from 'node:assert';
import { importProfileToSnapshot } from '../src/utils/organizerDefaults.js';
import { computeRebuildReadiness } from '../src/utils/rebuildReadiness.js';
import { normalizeSelectedRoots } from '../src/utils/rootCardinality.js';

describe('Gate5-C-hotfix3 Frontend Regression & Contract Tests', () => {
  describe('P2-13: Stale Rebuild Refresh Readiness State Machine', () => {
    it('1. Initial successful preview allows rebuild with accepted digest', () => {
      const state = computeRebuildReadiness({
        hasPreview: true,
        previewInvalidated: false,
        acceptedDigest: 'a'.repeat(64),
        isLoading: false,
        isFetching: false,
      });
      assert.strictEqual(state.canSubmit, true);
      assert.strictEqual(state.submitDigest, 'a'.repeat(64));
    });

    it('2. PREVIEW_CHANGED invalidates old digest and disables rebuild button', () => {
      const state = computeRebuildReadiness({
        hasPreview: true,
        previewInvalidated: true,
        acceptedDigest: null,
        isLoading: false,
        isFetching: false,
      });
      assert.strictEqual(state.canSubmit, false);
      assert.strictEqual(state.submitDigest, null);
    });

    it('3. While manual refresh is pending (isFetching=true), rebuild remains strictly disabled', () => {
      const state = computeRebuildReadiness({
        hasPreview: true,
        previewInvalidated: true,
        acceptedDigest: null,
        isLoading: false,
        isFetching: true,
      });
      assert.strictEqual(state.canSubmit, false);
      assert.strictEqual(state.submitDigest, null);
    });

    it('4. If refresh fails or errors, rebuild remains strictly disabled with no digest', () => {
      const state = computeRebuildReadiness({
        hasPreview: true,
        previewInvalidated: true,
        acceptedDigest: null,
        isLoading: false,
        isFetching: false,
      });
      assert.strictEqual(state.canSubmit, false);
      assert.strictEqual(state.submitDigest, null);
    });

    it('5. Only when refresh succeeds with new digest B, rebuild is enabled and submits digest B', () => {
      const state = computeRebuildReadiness({
        hasPreview: true,
        previewInvalidated: false,
        acceptedDigest: 'b'.repeat(64),
        isLoading: false,
        isFetching: false,
      });
      assert.strictEqual(state.canSubmit, true);
      assert.strictEqual(state.submitDigest, 'b'.repeat(64));
    });
  });

  describe('P2-14: Root Selector Cardinality & Mode Reset', () => {
    it('1. Organizer mode enforces exactly 1 root and caps [1, 2] to [1]', () => {
      const normalized = normalizeSelectedRoots([1, 2], 'organizer');
      assert.deepStrictEqual(normalized, [1]);
    });

    it('2. File mode allows 16 roots', () => {
      const roots16 = Array.from({ length: 16 }, (_, i) => i + 1);
      const normalized = normalizeSelectedRoots(roots16, 'file');
      assert.strictEqual(normalized?.length, 16);
      assert.deepStrictEqual(normalized, roots16);
    });

    it('3. File mode strictly blocks/caps 17th root to 16 roots', () => {
      const roots17 = Array.from({ length: 17 }, (_, i) => i + 1);
      const normalized = normalizeSelectedRoots(roots17, 'file');
      assert.strictEqual(normalized?.length, 16);
      assert.deepStrictEqual(normalized, roots17.slice(0, 16));
    });

    it('4. Empty or undefined roots returns undefined', () => {
      assert.strictEqual(normalizeSelectedRoots([], 'file'), undefined);
      assert.strictEqual(normalizeSelectedRoots(undefined, 'file'), undefined);
      assert.strictEqual(normalizeSelectedRoots([], 'organizer'), undefined);
      assert.strictEqual(normalizeSelectedRoots(undefined, 'organizer'), undefined);
    });
  });

  describe('P2-15: Organizer Profile Import Fresh Snapshot Independence', () => {
    it('1. Directly tests production importProfileToSnapshot helper without local duplicate', () => {
      const mockApiProfile = {
        id: 99,
        user_id: 1,
        slug: 'legacy-slug',
        builtin_version: 1,
        name: 'Fresh Profile v2',
        description: 'Profile updated on server',
        root: '/data/photos',
        recursive: true,
        image_extensions: ['jpg', 'png', 'webp', 'avif'],
        video_extensions: ['mp4', 'mkv'],
        rename_template: '{name}_v2',
        statistics_template: '[{images}P {size}]',
        preserve_tags: ['tag_v2'],
        cleanup_patterns: ['.*\\.bak'],
        numbering_mode: 'sequential' as const,
        numbering_start: 10,
        numbering_padding: 4,
        mtime_mode: 'ordered' as const,
        mtime_delay_seconds: 5.0,
        source_profile_id: 99,
        created_at: '2026-09-07T00:00:00Z',
        updated_at: '2026-09-07T12:00:00Z',
      };

      const snapshot = importProfileToSnapshot(mockApiProfile);

      // Verify canonical 14 fields preserved
      assert.strictEqual(snapshot.name, 'Fresh Profile v2');
      assert.strictEqual(snapshot.recursive, true);
      assert.deepStrictEqual(snapshot.image_extensions, ['jpg', 'png', 'webp', 'avif']);
      assert.deepStrictEqual(snapshot.video_extensions, ['mp4', 'mkv']);
      assert.strictEqual(snapshot.rename_template, '{name}_v2');
      assert.strictEqual(snapshot.statistics_template, '[{images}P {size}]');
      assert.deepStrictEqual(snapshot.preserve_tags, ['tag_v2']);
      assert.deepStrictEqual(snapshot.cleanup_patterns, ['.*\\.bak']);
      assert.strictEqual(snapshot.numbering_mode, 'sequential');
      assert.strictEqual(snapshot.numbering_start, 10);
      assert.strictEqual(snapshot.numbering_padding, 4);
      assert.strictEqual(snapshot.mtime_mode, 'ordered');
      assert.strictEqual(snapshot.mtime_delay_seconds, 5.0);

      // Verify sensitive/live binding keys are NOT in snapshot
      assert.strictEqual('id' in snapshot, false);
      assert.strictEqual('source_profile_id' in snapshot, false);
      assert.strictEqual('user_id' in snapshot, false);
      assert.strictEqual('slug' in snapshot, false);
      assert.strictEqual('builtin_version' in snapshot, false);
      assert.strictEqual('created_at' in snapshot, false);
      assert.strictEqual('updated_at' in snapshot, false);
    });

    it('2. Subsequent mutations to original profile do not affect immutable snapshot', () => {
      const source = {
        name: 'Original',
        recursive: false,
        image_extensions: ['jpg'],
        video_extensions: ['mp4'],
        rename_template: '{name}',
        statistics_template: '[{images}P]',
        preserve_tags: ['a'],
        cleanup_patterns: [],
        numbering_mode: 'none' as const,
        numbering_start: 1,
        numbering_padding: 3,
        mtime_mode: 'none' as const,
        mtime_delay_seconds: 2.0,
      };

      const snapshot = importProfileToSnapshot(source);

      // Mutate source arrays
      source.preserve_tags.push('b');
      source.image_extensions.push('png');
      source.name = 'Mutated Original';

      // Snapshot remains intact
      assert.deepStrictEqual(snapshot.preserve_tags, ['a']);
      assert.deepStrictEqual(snapshot.image_extensions, ['jpg']);
      assert.strictEqual(snapshot.name, 'Original');
    });
  });
});
