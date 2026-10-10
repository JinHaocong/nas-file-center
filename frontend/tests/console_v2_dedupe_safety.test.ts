import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { canSelectStorageAction, canRunCapabilityProbe } from '../src/components/dedupe/storageActionModel';
import {
  formatQuarantineRootPresentation, formatAllowedRootPresentation,
  getProtectLastFileDescription,
} from '../src/utils/dedupePresentation';
const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');

describe('Console v2 advanced dedupe identity and storage safety', () => {
  test('storage action remains role guarded and disabled state fails closed', () => {
    assert.equal(canSelectStorageAction('quarantine', false, false), true);
    assert.equal(canSelectStorageAction('hardlink', false, false), false);
    assert.equal(canSelectStorageAction('reflink', false, false), false);
    assert.equal(canSelectStorageAction('hardlink', true, false), true);
    assert.equal(canSelectStorageAction('reflink', true, false), true);
    assert.equal(canSelectStorageAction('quarantine', true, true), false);
    assert.equal(canSelectStorageAction('hardlink', true, true), false);
  });

  test('capability probe requires admin, explicit nonbusy action and preview path pair', () => {
    for (const action of ['hardlink','reflink'] as const) {
      assert.equal(canRunCapabilityProbe(action,true,false,false,true),true);
      assert.equal(canRunCapabilityProbe(action,false,false,false,true),false);
      assert.equal(canRunCapabilityProbe(action,true,true,false,true),false);
      assert.equal(canRunCapabilityProbe(action,true,false,true,true),false);
      assert.equal(canRunCapabilityProbe(action,true,false,false,false),false);
    }
    assert.equal(canRunCapabilityProbe('quarantine',true,false,false,true),false);
  });

  test('identity panel distinguishes preview and compile authorities without recomputing any digest', () => {
    const s=read('src/components/dedupe/DedupeIdentitySafetyPanel.tsx');
    for (const token of [
      'authorityType', "'preview_digest'", "'compile_digest'",
      '权威预览摘要 (preview_digest)', '工作流编译摘要 (compile_digest)',
      'dedupePreviewDigest', 'workflowRevision', 'definitionSha256',
      'runtimeScanJobId', 'scorerConfigDigest', 'sourceSnapshotDigest',
      'decisionDigest', 'previewSource', 'engineVersion',
      'liveFilesystemVerified = false', 'Pre-Freeze Draft Preview',
      'Live Filesystem Verified', 'SHA-256', 'Freeze → Validate → Execute',
      'formatQuarantineRootPresentation', 'formatAllowedRootPresentation',
      'getProtectLastFileDescription', 'protect_last_file',
      'allowed_roots', 'quarantine_root', 'navigator.clipboard.writeText',
      'onCopy(value)', 'role="note"', 'CodePath', '<dl',
    ]) assert.ok(s.includes(token),token);
    assert.doesNotMatch(s,/from ['"]antd['"]|@ant-design\/icons|<Card\b|<Descriptions\b|<Alert\b/);
    assert.equal(formatQuarantineRootPresentation(undefined), '未配置 / null');
    assert.equal(formatAllowedRootPresentation(1,'/mnt/allowed'),'Allowed Root 1: /mnt/allowed');
    assert.match(getProtectLastFileDescription(true),/PROTECT_LAST_FILE 已启用/);
    assert.match(getProtectLastFileDescription(false),/PROTECT_LAST_FILE 未启用/);
  });

  test('storage panel cannot auto-probe and retains backend diagnostics / risk language', () => {
    const s=read('src/components/dedupe/DedupeStorageActionPanel.tsx');
    for (const token of [
      'React.useId()', 'name={instanceId +', 'onChange(next)',
      'canSelectStorageAction(next, isAdmin, disabled)',
      'canRunCapabilityProbe(value, isAdmin, disabled, capabilityLoading, Boolean(diagnosticPair))',
      'onProbeCapabilities()', 'capabilityData?.[value]', 'capabilityLoading',
      'diagnosticPair.keepParent', 'diagnosticPair.sourceParent',
      'source_parent_device', 'source_parent_inode', 'parent_device', 'parent_inode',
      'SUPPORTED', 'UNSUPPORTED', 'UNKNOWN', 'NOT CHECKED',
      '只读', 'Hardlink', 'Reflink',
      '未来通过任一路径写入都会修改同一份文件内容',
      'Copy-on-Write', '仅管理员可生成、冻结、验证和执行',
      'disposable probe', '不会在 Preview / Generate 中自动运行',
      'Validate / Worker Execute', '能力探测失败', '<ConsoleButton',
    ].filter(v=>v!=='只读')) assert.ok(s.includes(token),token);
    assert.match(s,/onClick=\{\(\) => \{[\s\S]*onProbeCapabilities\(\)/);
    assert.doesNotMatch(s,/useEffect|from ['"]antd['"]|@ant-design\/icons|<Radio\b|<Descriptions\b|<Alert\b/);
  });

  test('shared scan page continues to gate preview digest and explicit probe', () => {
    const p=read('src/pages/Scans/AdvancedDedupePage.tsx');
    for(const token of [
      'DedupeIdentitySafetyPanel','DedupeStorageActionPanel',
      'onProbeCapabilities={() => capabilityMutation.mutate()}',
      'storageOptimizationApi.probeCapabilities',
      'expected_preview_digest: dedupeState.acceptedPreviewDigest',
      'canGeneratePlan(dedupeState)', 'PREVIEW_CHANGED',
    ])assert.ok(p.includes(token),token);
    const css=read('src/styles/console-v2-dedupe-safety.css');
    const main=read('src/main.tsx');
    for(const token of ['.nfc-v2-identity-panel','.nfc-v2-storage-action',
      '.nfc-v2-safety-facts','.nfc-v2-storage-capability-facts',
      "[data-theme='dark']",':focus-visible','@media (max-width: 767px)',
      'prefers-reduced-motion: reduce','min-height: 44px'])assert.ok(css.includes(token),token);
    assert.ok(main.includes("import './styles/console-v2-dedupe-safety.css';"));
  });
});
