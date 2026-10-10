import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { OrganizerProfile } from '../src/types';
import { createDefaultOrganizerSnapshot } from '../src/utils/organizerDefaults';
import { initialOrganizerProfileForm, organizerProfileFormPayload, canSubmitOrganizerProfileForm } from '../src/utils/organizerProfileForm';
import { patchWorkflowOrganizerAdvancedRule } from '../src/utils/workflowOrganizerSnapshot';
const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const existing: OrganizerProfile = {
  id: 22, user_id: 7, slug: null, builtin_version: null,
  name: '我的方案', description: '照片整理', root: '/nas/photos', recursive: true,
  image_extensions: ['jpg', 'heic'], video_extensions: ['mp4'],
  rename_template: '{index} {name}', statistics_template: '[{images}P]',
  preserve_tags: ['精选'], cleanup_patterns: ['old[-_]'],
  numbering_mode: 'sequential', numbering_start: 4, numbering_padding: 3,
  mtime_mode: 'ordered', mtime_delay_seconds: 2.5,
  advanced_rules: {
    version: 1,
    directory_depth: { enabled: true, rename_from_depth: 3 },
    file_numbering: { enabled: true, start: 2, padding: 4, sort: 'natural_name', extension_mode: 'preserve' },
    latest_child_prefix: { enabled: false, prefix: 'New ', timestamp: 'mtime_ns' },
    single_child_wrapper_collapse: { enabled: false, wrapper_depth: 2, child_type: 'directory' },
  },
  is_builtin: false, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
};
describe('Console v2 Organizer profile CRUD Radix form', () => {
  test('new mode loads canonical defaults without saved server identity', () => {
    assert.deepEqual(initialOrganizerProfileForm(null), createDefaultOrganizerSnapshot());
  });
  test('edit mode preserves all fields and deep clones nested structures', () => {
    const draft = initialOrganizerProfileForm(existing);
    for (const field of ['root','recursive','image_extensions','video_extensions','rename_template','statistics_template','preserve_tags','cleanup_patterns','numbering_mode','numbering_start','numbering_padding','mtime_mode','mtime_delay_seconds','advanced_rules'] as const) {
      assert.deepEqual(draft[field], existing[field], field);
    }
    assert.notEqual(draft.image_extensions, existing.image_extensions);
    assert.notEqual(draft.advanced_rules, existing.advanced_rules);
    draft.advanced_rules!.directory_depth.rename_from_depth = 18;
    assert.equal(existing.advanced_rules!.directory_depth.rename_from_depth, 3);
  });
  test('payload is allowlisted only; server identity, builtin and times cannot be overwritten', () => {
    const payload = organizerProfileFormPayload(initialOrganizerProfileForm(existing));
    assert.deepEqual(Object.keys(payload).sort(), ['name','description','root','recursive','image_extensions','video_extensions','rename_template','statistics_template','preserve_tags','cleanup_patterns','numbering_mode','numbering_start','numbering_padding','mtime_mode','mtime_delay_seconds','advanced_rules'].sort());
    assert.equal(payload.root, '/nas/photos');
    assert.equal(payload.advanced_rules!.file_numbering.sort, 'natural_name');
    assert.equal(payload.advanced_rules!.file_numbering.extension_mode, 'preserve');
    assert.equal(payload.advanced_rules!.latest_child_prefix.timestamp, 'mtime_ns');
    assert.equal(payload.advanced_rules!.single_child_wrapper_collapse.wrapper_depth, 2);
    assert.equal(payload.advanced_rules!.single_child_wrapper_collapse.child_type, 'directory');
    assert.notEqual(payload.advanced_rules, existing.advanced_rules);
  });
  test('blank optional root and description preserve prior Ant Form wire semantics', () => {
    const data = organizerProfileFormPayload(createDefaultOrganizerSnapshot('全局'));
    assert.equal(data.root, '');
    assert.equal(data.description, '');
    assert.equal(data.numbering_start, 1);
    assert.equal(data.mtime_delay_seconds, 2);
  });
  test('fail closed on builtins, busy state and invalid advanced combinations', () => {
    const draft = initialOrganizerProfileForm(existing);
    assert.equal(canSubmitOrganizerProfileForm(draft, existing, false), true);
    assert.equal(canSubmitOrganizerProfileForm(draft, { ...existing, is_builtin: true }, false), false);
    assert.equal(canSubmitOrganizerProfileForm(draft, existing, true), false);
    assert.equal(canSubmitOrganizerProfileForm({ ...draft, name: '' }, existing, false), false);
    assert.equal(canSubmitOrganizerProfileForm({ ...draft, recursive: false }, existing, false), false);
    const invalid = patchWorkflowOrganizerAdvancedRule(draft, 'latest_child_prefix', { enabled: true, prefix: '' });
    assert.equal(canSubmitOrganizerProfileForm(invalid, existing, false), false);
  });
  test('default root uses native DirectoryPicker and remains in allowed-roots backend authority', () => {
    const s = read('src/components/workflows/OrganizerSnapshotFields.tsx');
    for (const term of ['includeRoot?: boolean','includeRoot = false','includeRoot && (','<DirectoryPicker multiple={false}',"patch('root', path)",'ALLOWED_ROOTS','disabled={readOnly}']) assert.ok(s.includes(term), term);
    const browser = read('src/components/DirectoryPicker/DirectoryPickerModal.tsx');
    assert.ok(browser.includes('isWithinDirectoryRoots'));
  });
  test('modal implements safe Radix close/submit and retains draft on failed mutation', () => {
    const s = read('src/pages/Organizer/ProfileFormModal.tsx');
    for (const term of [
      "from '@radix-ui/react-dialog'",'<Dialog.Root','<Dialog.Portal','<Dialog.Overlay','<Dialog.Content',
      '<Dialog.Title','<Dialog.Description','<OrganizerSnapshotFields includeRoot',
      'initialOrganizerProfileForm(editingProfile)','organizerProfileFormPayload(draft)',
      'validateWorkflowOrganizerSnapshot(draft)','canSubmitOrganizerProfileForm(draft, editingProfile',
      'savingRef.current','if (busy || savingRef.current) return','onPointerDownOutside={event => event.preventDefault()}',
      'onEscapeKeyDown={event =>','await onSubmit(', 'type="submit"','noValidate',
    ]) assert.ok(s.includes(term), term);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Modal\b|<Form\b/);
  });
  test('the mutation parent keeps real create/update API and Preview/Plan separation', () => {
    const s = read('src/pages/Organizer/index.tsx');
    assert.ok(s.includes('organizerProfilesApi.createProfile(values)'));
    assert.ok(s.includes('organizerProfilesApi.updateProfile(editingProfile.id, values)'));
    assert.ok(s.includes("queryClient.invalidateQueries({ queryKey: ['organizer-profiles'] })"));
    const modal = read('src/pages/Organizer/ProfileFormModal.tsx');
    assert.doesNotMatch(modal, /createPlan|executePlan|filesystemApi\./);
  });
  test('profile dialog CSS is scoped and nested DirectoryPicker stacks above it', () => {
    const css = read('src/styles/console-v2-organizer-profile-form.css');
    for (const term of [
      '.nfc-v2-organizer-profile-overlay','z-index: 1140','.nfc-v2-organizer-profile-dialog',
      'z-index: 1141','.nfc-v2-organizer-root-field',"[data-theme='dark']",
      ':focus-visible','@media (max-width: 767px)','min-height: 44px',
      '@media (prefers-reduced-motion: reduce)',
    ]) assert.ok(css.includes(term), term);
    assert.ok(read('src/styles/console-v2-directory-modal.css').includes('z-index: 1201'));
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-organizer-profile-form.css';"));
  });
});
