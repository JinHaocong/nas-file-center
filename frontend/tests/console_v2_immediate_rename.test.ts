import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { RenameProposal } from '../src/types';
import {
  buildImmediateRenameRequest, canCreateImmediateRenamePlan,
  DEFAULT_IMMEDIATE_RENAME_DRAFT,
} from '../src/utils/immediateRenameSafety';
const read = (p: string) => readFileSync(resolve(process.cwd(),p), 'utf8');
const safe: RenameProposal = { source:'/nas/in/old.jpg',target:'/nas/in/new.jpg',conflict:false };

describe('Console v2 immediate file/directory Rename native editor', () => {
  test('canonical directory payload preserves exact literal replacement and excludes file flag', () => {
    const draft={...DEFAULT_IMMEDIATE_RENAME_DRAFT,parent:'/nas/media',find:'old',value:''};
    assert.deepEqual(buildImmediateRenameRequest('directory',draft),{
      parent:'/nas/media',mode:'replace_name',find:'old',value:'',
    });
    assert.deepEqual(buildImmediateRenameRequest('directory',{...draft,replaceTarget:'suffix'}),{
      parent:'/nas/media',mode:'replace_suffix',find:'old',value:'',
    });
  });
  test('file default protects last extension and opt-out preserves existing API field', () => {
    const draft={...DEFAULT_IMMEDIATE_RENAME_DRAFT,parent:'/nas/files',find:'old',value:'new'};
    assert.deepEqual(buildImmediateRenameRequest('file',draft),{
      parent:'/nas/files',mode:'replace_name',find:'old',value:'new',preserve_extension:true,
    });
    assert.equal(buildImmediateRenameRequest('file',{...draft,preserveExtension:false})?.preserve_extension,false);
  });
  test('add-prefix/add-suffix payloads and required literal validation', () => {
    const draft={...DEFAULT_IMMEDIATE_RENAME_DRAFT,parent:'/nas/in',module:'add' as const,value:'2026_'};
    assert.equal(buildImmediateRenameRequest('directory',draft)?.mode,'add_prefix');
    assert.equal(buildImmediateRenameRequest('file',{...draft,addPosition:'suffix'})?.mode,'add_suffix');
    assert.equal(buildImmediateRenameRequest('file',{...draft,value:''}),null);
    assert.equal(buildImmediateRenameRequest('directory',{...draft,find:'',module:'replace'}),null);
    assert.equal(buildImmediateRenameRequest('directory',{...draft,parent:'  '}),null);
  });
  test('Plan gate requires valid latest preview key, a nonempty list and zero conflicts', () => {
    assert.equal(canCreateImmediateRenamePlan([safe],'request',false),true);
    assert.equal(canCreateImmediateRenamePlan([safe],null,false),false);
    assert.equal(canCreateImmediateRenamePlan([safe],'request',true),false);
    assert.equal(canCreateImmediateRenamePlan(null,'request',false),false);
    assert.equal(canCreateImmediateRenamePlan([],'request',false),false);
    assert.equal(canCreateImmediateRenamePlan([{...safe,conflict:true}],'request',false),false);
    assert.equal(canCreateImmediateRenamePlan([{...safe,target:safe.source}],'request',false),false);
    assert.equal(canCreateImmediateRenamePlan([{...safe,target:''}],'request',false),false);
  });
  test('both existing entry point exports now route through common semantic editor', () => {
    const dir=read('src/pages/Rename/ImmediateDirectoryRename.tsx');
    const file=read('src/pages/Rename/ImmediateFileRename.tsx');
    assert.ok(dir.includes('<ImmediateRenameEditor kind="directory"'));
    assert.ok(file.includes('<ImmediateRenameEditor kind="file"'));
    assert.doesNotMatch(dir+file,/from ['"]antd['"]|@ant-design\/icons/);
    const main=read('src/pages/Rename/index.tsx');
    assert.ok(main.includes('<ImmediateDirectoryRename'));
    assert.ok(main.includes('<ImmediateFileRename'));
  });
  test('native editor safeguards invalidation, stale preview and exact Plan payload', () => {
    const s=read('src/pages/Rename/ImmediateRenameEditor.tsx');
    for(const token of [
      'batchApi.previewImmediateDirectoryRename', 'batchApi.previewImmediateFileRename',
      'plansApi.createPlan', 'previewGuard.current','planGuard.current',
      'activePreviewKey.current = null','setProposals(null)',
      'if (activePreviewKey.current !== key) return',
      'key !== activePreviewKey.current', 'canCreateImmediateRenamePlan',
      "name: `一级${label}批量重命名`", "kind: 'rename'",
      "operation: 'rename'", 'items = proposals.map',
      'preserve_extension: request.preserve_extension !== false',
      '<DirectoryPicker multiple={false}', 'buildImmediateRenameRequest',
      'typeof path === \'string\'', 'invalidatePreview();',
      'onChange={event => patch(', 'role="alert"',
    ]) assert.ok(s.includes(token),token);
    assert.doesNotMatch(s,/from ['"]antd['"]|@ant-design\/icons|<Table\b|<Radio\b|<Form\b/);
  });
  test('native form has four literal modes, readonly result and shared desktop/mobile pagination', () => {
    const s=read('src/pages/Rename/ImmediateRenameEditor.tsx');
    for(const token of [
      "'replace'", "'add'", "'prefix'", "'suffix'", 'replaceTarget',
      '<ConsoleButton','<ConsolePagination','<ConsoleEmpty','<ResponsiveDataView',
      '<StatusBadge','<CodePath','nfc-v2-immediate-table',
      'nfc-rename-proposal-mobile-card', 'getPaginationState',
      'visible.map(', 'aria-label={name}', 'maxLength={255}',
      'checked={draft.preserveExtension}', 'Preview', 'Plan',
    ]) assert.ok(s.includes(token),token);
  });
  test('scoped CSS has mobile tap targets, dark, focus and reduced-motion', () => {
    const css=read('src/styles/console-v2-immediate-rename.css');
    for(const token of [
      '.nfc-v2-immediate-rename','.nfc-v2-immediate-radio',
      '.nfc-v2-immediate-error','.nfc-v2-immediate-table',
      '.nfc-v2-immediate-mobile-list',
      "[data-theme='dark']",':focus-visible',
      '@media (max-width:767px)', 'min-height:44px',
      '@media (prefers-reduced-motion:reduce)',
    ]) assert.ok(css.includes(token),token);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-immediate-rename.css';"));
  });
});
