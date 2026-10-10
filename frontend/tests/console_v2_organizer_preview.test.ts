import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  canGenerateOrganizerPlan, organizerActionableChanges, organizerStageActionCount,
  organizerPreviewStageLabel, organizerProposalRuleLabel, organizerProposalStageLabel,
  type OrganizerPreviewPlanState,
} from '../src/utils/organizerPreviewSafety';
import type { OrganizerPreviewSummary, OrganizerProposal } from '../src/types';
const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');
const summary: OrganizerPreviewSummary = {
  total_directories: 12, changed_directories: 4, advanced_changes: 6,
  conflicts: 0, total_bytes: 12000, wrapper_candidates: 2,
};
const base: OrganizerPreviewPlanState = {
  summary, advancedEnabled: false, structuralRequired: false,
  previewRoot: '/nas/photos', selectedRoot: '/nas/photos', busy: false,
};

describe('Console v2 native Organizer staged Preview and Plan safety', () => {
  test('standard mode requires matching current root, positive action count, zero conflicts', () => {
    assert.equal(canGenerateOrganizerPlan(base, 'none'), true);
    assert.equal(canGenerateOrganizerPlan({ ...base, selectedRoot: '/nas/movies' }, 'none'), false);
    assert.equal(canGenerateOrganizerPlan({ ...base, previewRoot: '' }, 'none'), false);
    assert.equal(canGenerateOrganizerPlan({ ...base, busy: true }, 'none'), false);
    assert.equal(canGenerateOrganizerPlan({ ...base, summary: null }, 'none'), false);
    assert.equal(canGenerateOrganizerPlan({ ...base, summary: { ...summary, conflicts: 1 } }, 'none'), false);
    assert.equal(canGenerateOrganizerPlan({ ...base, summary: { ...summary, advanced_changes: 0, changed_directories: 0 } }, 'none'), false);
  });
  test('advanced preview must bind to nonempty digest even if Stage A structural', () => {
    const advanced = { ...base, advancedEnabled: true, structuralRequired: true };
    assert.equal(canGenerateOrganizerPlan(advanced, 'none'), false);
    assert.equal(canGenerateOrganizerPlan({ ...advanced, previewDigest: 'sha256:abc' }, 'none'), true);
    assert.equal(canGenerateOrganizerPlan({ ...advanced, previewDigest: 'sha256:abc', summary: { ...summary, conflicts: 2 } }, 'none'), false);
    assert.equal(organizerPreviewStageLabel(true, true), 'Stage A · Structural');
    assert.equal(organizerPreviewStageLabel(true, false), 'Stage B · Rename');
    assert.equal(organizerPreviewStageLabel(false, false), 'Standard');
  });
  test('mtime-only plan follows original threshold while avoiding empty/stale preview', () => {
    const clean = { ...base, summary: { ...summary, changed_directories: 0, advanced_changes: 0 } };
    assert.equal(canGenerateOrganizerPlan(clean, 'none'), false);
    assert.equal(canGenerateOrganizerPlan(clean, 'ordered'), true);
    assert.equal(canGenerateOrganizerPlan({ ...clean, summary: { ...clean.summary, total_directories: 0 } }, 'ordered'), false);
  });
  test('stage action counters preserve advanced changes and wrapper-only semantics', () => {
    assert.equal(organizerActionableChanges(summary), 6);
    assert.equal(organizerStageActionCount(summary, true), 2);
    assert.equal(organizerStageActionCount(summary, false), 6);
    assert.equal(organizerStageActionCount(null, true), 0);
    assert.equal(organizerActionableChanges(null), 0);
  });
  test('stage badges distinguish wrapper collapse, rename, file, prefix, touch', () => {
    const proposal = { proposal_type: 'wrapper_collapse' } as OrganizerProposal;
    assert.equal(organizerProposalStageLabel(proposal, true), 'Stage A');
    assert.equal(organizerProposalStageLabel(proposal, false), 'Standard');
    assert.equal(organizerProposalRuleLabel(proposal), 'Wrapper collapse');
    assert.equal(organizerProposalRuleLabel({ ...proposal, proposal_type:'file_rename' }), 'File numbering');
    assert.equal(organizerProposalRuleLabel({ ...proposal, proposal_type:'latest_child_prefix' }), 'Latest prefix');
    assert.equal(organizerProposalRuleLabel({ ...proposal, proposal_type:'touch' }), 'mtime');
    assert.equal(organizerProposalStageLabel({ ...proposal, proposal_type:'directory_rename' }, true), 'Stage B');
  });
  test('root invalidation and request epochs prevent stale digest acceptance', () => {
    const s = read('src/pages/Organizer/ProfilePreview.tsx');
    for (const token of [
      'sequenceRef.current += 1', 'clearPreview();', 'setPreviewDigest(undefined)',
      'setSnapshotId(undefined)', 'setPreviewRoot(\'\')',
      'if (requestId !== sequenceRef.current) return',
      'params.snapshotId !== result.snapshot_id',
      'previewInFlight.current', 'planInFlight.current',
      'previewRoot, selectedRoot: currentRoot, busy',
      'onChange={path =>', 'handleRootChange(path)',
    ]) assert.ok(s.includes(token), token);
  });
  test('native page retains readonly Preview snapshot pagination and digest-bound Plan API', () => {
    const s = read('src/pages/Organizer/ProfilePreview.tsx');
    for (const token of [
      'organizerProfilesApi.previewProfile(profile.id', 'snapshot_id: params.snapshotId',
      "only_changed: params.filter === 'changed'",
      "only_conflicts: params.filter === 'conflicts'",
      'organizerProfilesApi.createPlan(profile.id', 'include_touch: profile.mtime_mode',
      'expected_preview_digest: params.expectedPreviewDigest',
      'canGeneratePlan', 'canGenerateOrganizerPlan',
      '<DirectoryPicker multiple={false}', 'ALLOWED_ROOTS',
      'Stage A Structural Preview', 'Stage B Rename Preview', 'Stage B 锁定',
      '必须重新 Preview', 'MOVE → rmdir_empty',
      '<ConsolePagination', '<ResponsiveDataView', '<StatusBadge',
      'nfc-organizer-proposal-mobile-card', 'nfc-v2-organizer-proposal-table',
      '<ConsoleEmpty', 'role="alert"', 'role="status"',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Table\b|<Pagination\b|<Radio\b|<Form\b|<Alert\b/);
  });
  test('scoped desktop/mobile/dark/focus styles are registered without Ant theme dependency', () => {
    const css = read('src/styles/console-v2-organizer-preview.css');
    for (const term of [
      '.nfc-v2-organizer-preview', '.nfc-v2-organizer-proposal-table',
      '.nfc-v2-organizer-proposal-mobile-list', '.nfc-v2-organizer-stage-notice',
      '.nfc-v2-organizer-filter', "[data-theme='dark']", ':focus-visible',
      '@media (max-width:767px)', 'min-height:44px', '@media (prefers-reduced-motion:reduce)',
    ]) assert.ok(css.includes(term), term);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-organizer-preview.css';"));
  });
});
