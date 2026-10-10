import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createDefaultOrganizerSnapshot, importProfileToSnapshot } from '../src/utils/organizerDefaults';
import {
  hydrateWorkflowOrganizerSnapshot, normalizeWorkflowOrganizerSnapshot,
  patchWorkflowOrganizerSnapshot, patchWorkflowOrganizerAdvancedRule,
  validateWorkflowOrganizerSnapshot,
} from '../src/utils/workflowOrganizerSnapshot';
const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 native Workflow Organizer immutable snapshot', () => {
  test('snapshot hydration retains old Ant Form defaults and deep clones arrays/rules', () => {
    const original = createDefaultOrganizerSnapshot('相册归档');
    original.preserve_tags = ['[精选]'];
    const view = hydrateWorkflowOrganizerSnapshot(original);
    assert.deepEqual(view, original);
    assert.notEqual(view.image_extensions, original.image_extensions);
    assert.notEqual(view.video_extensions, original.video_extensions);
    assert.notEqual(view.preserve_tags, original.preserve_tags);
    assert.notEqual(view.cleanup_patterns, original.cleanup_patterns);
    assert.notEqual(view.advanced_rules, original.advanced_rules);
    assert.notEqual(view.advanced_rules!.file_numbering, original.advanced_rules!.file_numbering);
    view.advanced_rules!.file_numbering.start = 92;
    assert.equal(original.advanced_rules!.file_numbering.start, 1);
  });
  test('normalization preserves original onValuesChange transport and all 4 advanced rules', () => {
    const view = createDefaultOrganizerSnapshot('原方案');
    view.description = '';
    view.root = '';
    const normalized = normalizeWorkflowOrganizerSnapshot(view);
    assert.equal(normalized.description, null);
    assert.equal(normalized.root, null);
    assert.equal(normalized.rename_template, '{name}');
    assert.equal(normalized.statistics_template, '[{images}P {videos}V {size}]');
    assert.deepEqual(normalized.advanced_rules, view.advanced_rules);
    const withDefaults = normalizeWorkflowOrganizerSnapshot({ name: 'x' });
    assert.deepEqual(withDefaults.image_extensions, ['jpg','jpeg','png','webp']);
    assert.deepEqual(withDefaults.video_extensions, ['mp4','mov','mkv']);
    assert.equal(withDefaults.advanced_rules!.single_child_wrapper_collapse.wrapper_depth, 2);
    assert.equal(withDefaults.advanced_rules!.single_child_wrapper_collapse.child_type, 'directory');
  });
  test('editing one field preserves unseen imported root and all advanced rule snapshots', () => {
    const imported = importProfileToSnapshot({
      name: '来源方案', root: '/nas/old', recursive: true,
      cleanup_patterns: ['\\[\\d+P\\]'],
      advanced_rules: {
        version: 1,
        directory_depth: { enabled: true, rename_from_depth: 3 },
        file_numbering: { enabled: false, start: 13, padding: 4, sort: 'natural_name', extension_mode: 'preserve' },
        latest_child_prefix: { enabled: false, prefix: 'Latest ', timestamp: 'mtime_ns' },
        single_child_wrapper_collapse: { enabled: false, wrapper_depth: 2, child_type: 'directory' },
      },
    });
    const updated = patchWorkflowOrganizerSnapshot(imported, 'description', '新描述');
    assert.equal(updated.root, '/nas/old');
    assert.deepEqual(updated.cleanup_patterns, imported.cleanup_patterns);
    assert.deepEqual(updated.advanced_rules, imported.advanced_rules);
    assert.notEqual(updated.advanced_rules, imported.advanced_rules);
    assert.equal(imported.description, '');
  });
  test('advanced field patch updates only selected fixed rule, with immutable nested copies', () => {
    const original = createDefaultOrganizerSnapshot('方案');
    const updated = patchWorkflowOrganizerAdvancedRule(original, 'latest_child_prefix', {
      enabled: true, prefix: 'Newest ',
    });
    assert.equal(updated.advanced_rules!.latest_child_prefix.enabled, true);
    assert.equal(updated.advanced_rules!.latest_child_prefix.prefix, 'Newest ');
    assert.equal(updated.advanced_rules!.latest_child_prefix.timestamp, 'mtime_ns');
    assert.equal(original.advanced_rules!.latest_child_prefix.enabled, false);
    assert.deepEqual(updated.advanced_rules!.file_numbering, original.advanced_rules!.file_numbering);
    const sorted = patchWorkflowOrganizerAdvancedRule(updated, 'file_numbering', { start: 17 });
    assert.equal(sorted.advanced_rules!.file_numbering.sort, 'natural_name');
    assert.equal(sorted.advanced_rules!.file_numbering.extension_mode, 'preserve');
  });
  test('warnings cover recursive, ordered mtime, missing prefix and reserved depth', () => {
    const base = createDefaultOrganizerSnapshot('工作流');
    assert.deepEqual(validateWorkflowOrganizerSnapshot(base), []);
    const advanced = patchWorkflowOrganizerAdvancedRule(base, 'directory_depth', { enabled: true, rename_from_depth: 1 });
    let errors = validateWorkflowOrganizerSnapshot(advanced);
    assert.ok(errors.some(x => x.includes('递归处理')));
    assert.ok(errors.some(x => x.includes('2 到 64')));
    const prefix = patchWorkflowOrganizerAdvancedRule({ ...base, recursive: true, mtime_mode: 'ordered' }, 'latest_child_prefix', {
      enabled: true, prefix: '',
    });
    errors = validateWorkflowOrganizerSnapshot(prefix);
    assert.ok(errors.some(x => x.includes('ordered mtime')));
    assert.ok(errors.some(x => x.includes('非空前缀')));
  });
  test('native Workflow editor imports fetched immutable snapshot and blocks readonly / parallel fetch', () => {
    const s = read('src/components/workflows/OrganizerStepEditor.tsx');
    for (const t of [
      '<OrganizerSnapshotFields', "queryKey: ['organizerProfilesListForImport']",
      'organizerProfilesApi.listProfiles(1, 100)', 'organizerProfilesApi.getProfile(profileId)',
      'importProfileToSnapshot(fresh)', 'profile_snapshot: immutableSnapshot',
      'profile_snapshot: nextSnapshot', 'readOnlyRef.current', 'importInFlight.current',
      'Number.isSafeInteger(profileId)', 'knownIds.includes(profileId)',
      'enabled: !readOnly', 'readOnly={readOnly || isImporting}', 'useConsoleToast',
      'aria-label="选择已有整理方案导入快照"', 'role="alert"',
    ]) assert.ok(s.includes(t), t);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Form\b|<Select\b|message\./);
    const shared = read('src/components/workflows/OrganizerProfileFields.tsx');
    assert.ok(shared.includes('Form.useFormInstance()')); // Standalone form stays untouched.
  });
  test('native tabs, advanced Stage A/B alerts and live template preview retain safe semantics', () => {
    const s = read('src/components/workflows/OrganizerSnapshotFields.tsx');
    for (const t of [
      "type Tab = 'basic' | 'template' | 'rules' | 'mtime' | 'advanced'",
      'role="tablist"', 'role="tab"', 'aria-selected={tab === item.key}',
      'onTabKey(event, i)', 'ArrowRight', 'ArrowLeft', 'Home', 'End',
      'renderTemplate(', 'formatBytes(', 'nfc-v2-organizer-live-preview',
      "'directory_depth'", "'file_numbering'", "'latest_child_prefix'",
      "'single_child_wrapper_collapse'", 'nfc-organizer-advanced-collapse',
      'aria-expanded={expandedRules.includes(key)}', 'hidden={!expandedRules.includes(key)}',
      'patchWorkflowOrganizerAdvancedRule', 'validateWorkflowOrganizerSnapshot',
      'Stage A', 'Stage B', 'MOVE → rmdir_empty', 'natural_name', 'mtime_ns',
      'role="alert"', 'disabled={readOnly}', 'readOnly &&',
      'cleanup_patterns', 'preserve_tags', 'image_extensions', 'video_extensions',
    ]) assert.ok(s.includes(t), t);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Form\b|<Tabs\b|<Collapse\b|<Switch\b/);
  });
  test('new CSS scopes dark/mobile, focus and reduced motion without changing profile CRUD', () => {
    const css = read('src/styles/console-v2-workflow-organizer.css');
    const main = read('src/main.tsx');
    for (const t of [
      '.nfc-v2-workflow-organizer', '.nfc-v2-workflow-organizer-import',
      '.nfc-v2-organizer-snapshot-form', '.nfc-v2-organizer-tabs',
      '.nfc-v2-organizer-rule', '.nfc-v2-organizer-rule-body[hidden]',
      ".nfc-v2-organizer-tabs button[aria-selected='true']",
      "[data-theme='dark']", ':focus-visible', '@media (max-width:767px)',
      'min-height:44px', '@media (prefers-reduced-motion:reduce)',
    ]) assert.ok(css.includes(t), t);
    assert.ok(main.includes("import './styles/console-v2-workflow-organizer.css';"));
  });
});
