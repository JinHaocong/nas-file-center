import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createDefaultOrganizerSnapshot } from '../src/utils/organizerDefaults';
import {
  hydrateWorkflowOrganizerSnapshot, patchWorkflowOrganizerSnapshot,
  patchWorkflowOrganizerAdvancedRule, validateWorkflowOrganizerSnapshot,
} from '../src/utils/workflowOrganizerSnapshot';
import {
  canSubmitOrganizerProfileForm, organizerProfileFormPayload,
} from '../src/utils/organizerProfileForm';

const read = (file: string) => readFileSync(resolve(process.cwd(), file), 'utf8');

describe('Console v2 native Organizer field authority', () => {
  test('active profile and workflow entry points use one native controlled editor', () => {
    const modal = read('src/pages/Organizer/ProfileFormModal.tsx');
    const step = read('src/components/workflows/OrganizerStepEditor.tsx');
    const editor = read('src/components/workflows/OrganizerSnapshotFields.tsx');
    for (const marker of [
      '<OrganizerSnapshotFields includeRoot', 'initialOrganizerProfileForm(editingProfile)',
      'organizerProfileFormPayload(draft)', 'readOnly={busy || !!editingProfile?.is_builtin}',
    ]) assert.ok(modal.includes(marker), marker);
    for (const marker of [
      '<OrganizerSnapshotFields value={step.profile_snapshot}',
      'importProfileToSnapshot(fresh)', 'profile_snapshot: nextSnapshot',
      'readOnly={readOnly || isImporting}',
    ]) assert.ok(step.includes(marker), marker);
    for (const marker of [
      'hydrateWorkflowOrganizerSnapshot(value)', 'patchWorkflowOrganizerAdvancedRule(',
      'validateWorkflowOrganizerSnapshot(snapshot)', 'role="tablist"',
      'aria-expanded={expandedRules.includes(key)}', '<DirectoryPicker multiple={false}',
      'renderTemplate(', 'Stage A', 'Stage B', 'MOVE → rmdir_empty',
    ]) assert.ok(editor.includes(marker), marker);
    assert.equal(existsSync(resolve(process.cwd(),
      'src/components/workflows/OrganizerProfileFields.tsx')), false);
    for (const source of [modal, step, editor]) {
      assert.doesNotMatch(source, /from ['"]antd['"]|@ant-design\/icons|Form\.useFormInstance|Form\.useWatch/);
    }
  });

  test('payload retains schema, regex strings, safety constants but no server identity', () => {
    const original = createDefaultOrganizerSnapshot('原方案');
    original.root = '/nas/media';
    original.cleanup_patterns = ['old[-_]'];
    original.preserve_tags = ['[精选]'];
    original.recursive = true;
    const draft = patchWorkflowOrganizerAdvancedRule(original, 'directory_depth',
      { enabled: true, rename_from_depth: 3 });
    const payload = organizerProfileFormPayload(draft);
    assert.deepEqual(Object.keys(payload).sort(), [
      'name','description','root','recursive','image_extensions','video_extensions',
      'rename_template','statistics_template','preserve_tags','cleanup_patterns',
      'numbering_mode','numbering_start','numbering_padding','mtime_mode',
      'mtime_delay_seconds','advanced_rules',
    ].sort());
    assert.deepEqual(payload.cleanup_patterns, original.cleanup_patterns);
    assert.deepEqual(payload.preserve_tags, original.preserve_tags);
    assert.equal(payload.advanced_rules?.directory_depth.rename_from_depth, 3);
    assert.equal(payload.advanced_rules?.single_child_wrapper_collapse.wrapper_depth, 2);
    assert.equal(payload.advanced_rules?.file_numbering.sort, 'natural_name');
    assert.equal(payload.advanced_rules?.latest_child_prefix.timestamp, 'mtime_ns');
    assert.notEqual(payload.advanced_rules, draft.advanced_rules);
    assert.equal(canSubmitOrganizerProfileForm(draft, null, false), true);
    assert.equal(canSubmitOrganizerProfileForm(draft, null, true), false);
  });

  test('changing a field never aliases an imported root, arrays or advanced rules', () => {
    const original = createDefaultOrganizerSnapshot('源方案');
    original.root = '/nas/archive';
    original.image_extensions = ['jpg','webp'];
    const named = patchWorkflowOrganizerSnapshot(original, 'name', '修改名称');
    const updated = patchWorkflowOrganizerAdvancedRule(named, 'file_numbering', { start: 17 });
    assert.equal(original.name, '源方案');
    assert.equal(updated.root, '/nas/archive');
    assert.deepEqual(updated.image_extensions, ['jpg','webp']);
    assert.notEqual(updated.image_extensions, original.image_extensions);
    assert.equal(updated.advanced_rules?.file_numbering.start, 17);
    assert.equal(original.advanced_rules?.file_numbering.start, 1);
    assert.notEqual(hydrateWorkflowOrganizerSnapshot(original).advanced_rules,
      original.advanced_rules);
  });

  test('all four advanced rules require recursion, with Stage A and mtime restrictions', () => {
    const names = [
      'directory_depth', 'file_numbering', 'latest_child_prefix',
      'single_child_wrapper_collapse',
    ] as const;
    const base = createDefaultOrganizerSnapshot('规则方案');
    for (const name of names) {
      const toggled = patchWorkflowOrganizerAdvancedRule(base, name, { enabled: true });
      assert.ok(validateWorkflowOrganizerSnapshot(toggled)
        .some(text => text.includes('递归处理')), name);
      assert.equal(base.advanced_rules![name].enabled, false);
    }
    const wrapper = patchWorkflowOrganizerAdvancedRule({ ...base, recursive: true },
      'single_child_wrapper_collapse', { enabled: true });
    assert.deepEqual(validateWorkflowOrganizerSnapshot(wrapper), []);
    assert.equal(wrapper.advanced_rules?.single_child_wrapper_collapse.child_type, 'directory');
    assert.equal(wrapper.advanced_rules?.single_child_wrapper_collapse.wrapper_depth, 2);
    const ordered = patchWorkflowOrganizerAdvancedRule(
      { ...base, recursive: true, mtime_mode: 'ordered' },
      'latest_child_prefix', { enabled: true, prefix: 'NEW ' });
    assert.ok(validateWorkflowOrganizerSnapshot(ordered)
      .some(text => text.includes('ordered mtime')));
    assert.equal(canSubmitOrganizerProfileForm(ordered, null, false), false);
    const depth = patchWorkflowOrganizerAdvancedRule(
      { ...base, recursive: true }, 'directory_depth',
      { enabled: true, rename_from_depth: 1 });
    assert.ok(validateWorkflowOrganizerSnapshot(depth)
      .some(text => text.includes('2 到 64')));
  });

  test('only ThemeContext remains allowlisted for direct AntD imports', () => {
    const guard = read('scripts/check-ant-design-tail.mjs');
    assert.ok(guard.includes("'src/contexts/ThemeContext.tsx'"));
    assert.ok(!guard.includes("'src/components/workflows/OrganizerProfileFields.tsx'"));
    assert.ok(guard.includes('const unexpected = matches.filter(item => !item.approved)'));
  });
});
