import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { OrganizerProfile } from '../src/types';
import { parseOrganizerProfileImport, resolveOrganizerProfileDelete, organizerExportFilename } from '../src/utils/organizerProfileListActions';
import { getPaginationState } from '../src/components/ui/paginationModel';
const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');
const personal = { id:21, name:'私人媒体', is_builtin:false } as OrganizerProfile;
const builtin = { id:2, name:'内置方案', is_builtin:true } as OrganizerProfile;

describe('Console v2 Organizer native catalog', () => {
  test('import JSON retains exported envelope and refuses malformed source', () => {
    const profile = { name:'相册', preserve_tags:['精选'] };
    assert.deepEqual(parseOrganizerProfileImport(JSON.stringify({schema_version:1,profile})),{schema_version:1,profile});
    for(const raw of ['null','[]','"str"','{}','{"schema_version":0,"profile":{}}',
      '{"schema_version":1.2,"profile":{}}','{"schema_version":1,"profile":null}',
      '{"schema_version":1,"profile":[]}','{"schema_version":1,"profile":"bad"}']) {
      assert.throws(() => parseOrganizerProfileImport(raw));
    }
    assert.throws(() => parseOrganizerProfileImport('{invalid'), SyntaxError);
  });
  test('delete confirmation prevents builtin, stale name/ID and in-flight delete', () => {
    const list=[personal,builtin];
    assert.deepEqual(resolveOrganizerProfileDelete({id:21,name:'私人媒体'},list,false),personal);
    assert.equal(resolveOrganizerProfileDelete({id:2,name:'内置方案'},list,false),null);
    assert.equal(resolveOrganizerProfileDelete({id:21,name:'旧名称'},list,false),null);
    assert.equal(resolveOrganizerProfileDelete({id:21,name:'私人媒体'},[builtin],false),null);
    assert.equal(resolveOrganizerProfileDelete({id:21,name:'私人媒体'},list,true),null);
    assert.equal(resolveOrganizerProfileDelete(null,list,false),null);
  });
  test('safe export filename and server pagination state', () => {
    assert.equal(organizerExportFilename('相册2026'),'organizer-profile-相册2026.json');
    assert.equal(organizerExportFilename('../etc/passwd'),'organizer-profile-.._etc_passwd.json');
    assert.equal(organizerExportFilename(' '),'organizer-profile-export.json');
    assert.ok(organizerExportFilename('a'.repeat(200)).length<=125);
    assert.deepEqual(getPaginationState(3,20,51),{pages:3,current:3,start:41,end:51});
  });
  test('same server query drives native responsive list and authorization recheck', () => {
    const s=read('src/pages/Organizer/ProfileList.tsx');
    for(const item of ["queryKey: ['organizer-profiles', page, pageSize, search]",
      'organizerProfilesApi.listProfiles(page, pageSize, search)',
      'organizerProfilesApi.cloneProfile(id)','organizerProfilesApi.deleteProfile(id)',
      'organizerProfilesApi.exportProfile(profile.id)','organizerProfilesApi.importProfile(payload)',
      'cloneMutation','deleteMutation','importMutation','handleExport',
      'resolveOrganizerProfileDelete(deleteIntent, items, false)',
      'deleteGuard.current','cloneGuard.current','importGuard.current',
      '<DataPanel','<ActionBar','<ResponsiveDataView','<ConsolePagination',
      '<ConsoleConfirmDialog','<ConsoleEmpty','<CodePath',
      'nfc-v2-organizer-table','nfc-organizer-profile-mobile-card',
      'items.map(profile =>','formatDateTime','profile.is_builtin','role="alert"',
      'aria-label="搜索整理方案"']) assert.ok(s.includes(item),item);
    assert.doesNotMatch(s,/from ['"]antd['"]|@ant-design\/icons|<Table\b|<Popconfirm\b|<Upload\b|<Pagination\b|<Modal\b/);
  });
  test('native JSON import validates before mutation and protects reading/closing', () => {
    const s=read('src/pages/Organizer/ProfileList.tsx');
    for(const item of ['<Dialog.Root','<Dialog.Portal','<Dialog.Title','<Dialog.Description',
      'onPointerDownOutside={event => event.preventDefault()}',
      'file.text()','file.size > 5 * 1024 * 1024',
      'fileReadToken.current','parseOrganizerProfileImport(importJsonText)',
      'importGuard.current','URL.createObjectURL','URL.revokeObjectURL',
      'accept=".json,application/json"','aria-label="方案 JSON 内容"']) assert.ok(s.includes(item),item);
  });
  test('scoped dark/mobile/keyboard CSS and registered test runner', () => {
    const css=read('src/styles/console-v2-organizer-profile-list.css');
    for(const item of ['.nfc-v2-organizer-table','.nfc-v2-organizer-mobile-list',
      '.nfc-v2-organizer-import-overlay','z-index:1170',
      '.nfc-v2-organizer-import-dialog','z-index:1171',
      "[data-theme='dark']",':focus-visible',
      '@media (max-width:767px)','min-height:44px','@media (prefers-reduced-motion:reduce)']) assert.ok(css.includes(item),item);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-organizer-profile-list.css';"));
  });
});
