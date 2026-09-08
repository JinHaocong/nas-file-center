import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  getEligibilityPresentation,
  formatOptionalGroupId,
  formatOptionalFileSize,
  canCompareDedupeGroup,
  findDuplicateGroupSiblings,
  formatQuarantineRootPresentation,
  formatAllowedRootPresentation,
  getProtectLastFileDescription,
} from '../src/utils/dedupePresentation';
import { dedupeStateReducer, canGeneratePlan, initialDedupeState } from '../src/utils/dedupeState';
import { formatDedupeErrorMessage, getStructuredApiError } from '../src/api/errors';

describe('Hotfix3 Section 1 & 3: Pure Presentation Helpers', () => {
  describe('getEligibilityPresentation', () => {
    it('eligible=true -> 符合资格 (eligible)', () => {
      const res = getEligibilityPresentation(true);
      assert.strictEqual(res.text, '符合资格');
      assert.strictEqual(res.status, 'eligible');
      assert.strictEqual(res.tagColor, 'success');
    });

    it('eligible=false -> 安全排除 (safety excluded)', () => {
      const res = getEligibilityPresentation(false);
      assert.strictEqual(res.text, '安全排除');
      assert.strictEqual(res.status, 'safety_excluded');
      assert.strictEqual(res.tagColor, 'warning');
    });

    it('eligible=undefined -> 不可用 / - (unavailable, never safety excluded)', () => {
      const res = getEligibilityPresentation(undefined);
      assert.strictEqual(res.text, '不可用 / -');
      assert.strictEqual(res.status, 'unavailable');
      assert.strictEqual(res.tagColor, 'default');
    });

    it('eligible=null -> 不可用 / - (unavailable)', () => {
      const res = getEligibilityPresentation(null as any);
      assert.strictEqual(res.text, '不可用 / -');
      assert.strictEqual(res.status, 'unavailable');
      assert.strictEqual(res.tagColor, 'default');
    });
  });

  describe('formatOptionalGroupId', () => {
    it('valid numeric group ID -> 组 #ID', () => {
      assert.strictEqual(formatOptionalGroupId(101), '组 #101');
      assert.strictEqual(formatOptionalGroupId(0), '组 #0');
    });

    it('undefined or null group ID -> 组 - (never 组 #undefined)', () => {
      assert.strictEqual(formatOptionalGroupId(undefined), '组 -');
      assert.strictEqual(formatOptionalGroupId(null), '组 -');
      assert.doesNotMatch(formatOptionalGroupId(undefined), /undefined/);
      assert.doesNotMatch(formatOptionalGroupId(null), /null/);
    });
  });

  describe('formatOptionalFileSize', () => {
    it('valid file size -> formatted string', () => {
      const formatted = formatOptionalFileSize(1048576);
      assert.match(formatted, /1.*MB|1024.*KB/);
      assert.strictEqual(formatOptionalFileSize(0), '0 B');
    });

    it('undefined or null file size -> - (strictly NOT 0 B)', () => {
      assert.strictEqual(formatOptionalFileSize(undefined), '-');
      assert.strictEqual(formatOptionalFileSize(null), '-');
      assert.notStrictEqual(formatOptionalFileSize(undefined), '0 B');
      assert.notStrictEqual(formatOptionalFileSize(null), '0 B');
    });
  });

  describe('canCompareDedupeGroup and findDuplicateGroupSiblings', () => {
    it('canCompareDedupeGroup returns true only when both IDs defined and equal', () => {
      assert.strictEqual(canCompareDedupeGroup({ group_provenance_id: 5 }, { group_provenance_id: 5 }), true);
      assert.strictEqual(canCompareDedupeGroup({ group_provenance_id: 5 }, { group_provenance_id: 6 }), false);
      assert.strictEqual(canCompareDedupeGroup({ group_provenance_id: undefined }, { group_provenance_id: undefined }), false);
      assert.strictEqual(canCompareDedupeGroup({ group_provenance_id: null }, { group_provenance_id: null }), false);
      assert.strictEqual(canCompareDedupeGroup({ group_provenance_id: 5 }, { group_provenance_id: undefined }), false);
    });

    it('findDuplicateGroupSiblings never groups missing group provenance rows together', () => {
      const current = { absolute_path: '/data/file1.txt', group_provenance_id: undefined };
      const allMembers = [
        { absolute_path: '/data/file1.txt', group_provenance_id: undefined },
        { absolute_path: '/data/file2.txt', group_provenance_id: undefined },
        { absolute_path: '/data/file3.txt', group_provenance_id: null as any },
        { absolute_path: '/data/file4.txt', group_provenance_id: 10 },
      ];
      const siblings = findDuplicateGroupSiblings(current, allMembers);
      assert.strictEqual(siblings.length, 0, 'Incomplete rows without provenance ID must have 0 siblings');
    });

    it('findDuplicateGroupSiblings groups rows with identical non-null group_provenance_id excluding self', () => {
      const current = { absolute_path: '/data/file1.txt', group_provenance_id: 42 };
      const allMembers = [
        { absolute_path: '/data/file1.txt', group_provenance_id: 42 },
        { absolute_path: '/data/file2.txt', group_provenance_id: 42 },
        { absolute_path: '/data/file3.txt', group_provenance_id: 43 },
        { absolute_path: '/data/file4.txt', group_provenance_id: undefined },
      ];
      const siblings = findDuplicateGroupSiblings(current, allMembers);
      assert.strictEqual(siblings.length, 1);
      assert.strictEqual(siblings[0].absolute_path, '/data/file2.txt');
    });
  });
});

describe('Hotfix3 Section 4 & 6: Identity and Safety Policy Presentation', () => {
  it('formatQuarantineRootPresentation returns backend path or 未配置 / null', () => {
    assert.strictEqual(formatQuarantineRootPresentation('/data/quarantine'), '/data/quarantine');
    assert.strictEqual(formatQuarantineRootPresentation(null), '未配置 / null');
    assert.strictEqual(formatQuarantineRootPresentation(undefined), '未配置 / null');
  });

  it('formatAllowedRootPresentation formats indexed allowed root', () => {
    assert.strictEqual(formatAllowedRootPresentation(0, '/nas/root1'), 'Allowed Root 0: /nas/root1');
    assert.strictEqual(formatAllowedRootPresentation(1, '/nas/root2'), 'Allowed Root 1: /nas/root2');
  });

  it('getProtectLastFileDescription returns strict directory-level protection semantics', () => {
    const enabledDesc = getProtectLastFileDescription(true);
    assert.match(enabledDesc, /PROTECT_LAST_FILE 已启用/);
    assert.match(enabledDesc, /目录级最后文件保护/);
    assert.match(enabledDesc, /避免计划隔离使受保护目录剩余文件数降到 0/);
    assert.match(enabledDesc, /具体排除原因以 backend safety_reasons 为准/);
    assert.doesNotMatch(enabledDesc, /确保每个重复组至少保留一个副本/);

    const disabledDesc = getProtectLastFileDescription(false);
    assert.strictEqual(disabledDesc, 'PROTECT_LAST_FILE 未启用。');
  });
});

describe('Hotfix3 Section 8: Fail Closed on Semantic Generate Errors', () => {
  it('dedupeStateReducer clears acceptedPreviewDigest and disables generate on GENERATE_FAILED', () => {
    let state = dedupeStateReducer(initialDedupeState, {
      type: 'PREVIEW_SUCCESS',
      digest: 'sha256:accepted-test-digest',
      requestGeneration: 1,
    });
    assert.strictEqual(canGeneratePlan(state), true);
    assert.strictEqual(state.acceptedPreviewDigest, 'sha256:accepted-test-digest');

    // Simulate generate started
    state = dedupeStateReducer(state, { type: 'GENERATE_STARTED' });

    // Simulate semantic generate failure (e.g. DEDUPE_SCAN_NOT_FOUND / DEDUPE_EMPTY_PLAN)
    state = dedupeStateReducer(state, {
      type: 'GENERATE_FAILED',
      error: 'DEDUPE_EMPTY_PLAN: 没有可执行的去重操作',
    });

    assert.strictEqual(state.acceptedPreviewDigest, null, 'acceptedPreviewDigest must be cleared to fail closed');
    assert.strictEqual(state.status, 'PREVIEW_STALE');
    assert.strictEqual(canGeneratePlan(state), false, 'Generate must be disabled');
  });
});

describe('Hotfix3 Section 9: DEDUPE_RESCAN_REQUIRED Error and Recovery Guidance', () => {
  it('formats DEDUPE_RESCAN_REQUIRED with exact 5-step recovery guidance', () => {
    const error = {
      detail: {
        error: {
          code: 'DEDUPE_RESCAN_REQUIRED',
          message: 'Scan generation mismatch',
        },
      },
    };
    const formatted = formatDedupeErrorMessage(error);
    assert.match(formatted, /DEDUPE_RESCAN_REQUIRED/);
    assert.match(formatted, /new scan → completed → return Workflow → select new Scan Job → Preview → Generate new Draft/);
  });
});
