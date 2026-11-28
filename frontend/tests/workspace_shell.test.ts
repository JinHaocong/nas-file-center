import assert from 'node:assert/strict';
import test from 'node:test';

import { navLabel, workspaceNavigationGroup, workspaceViewKey } from '../src/components/layout/navItems';

test('cloud files has its own destination beside local files', () => {
  assert.equal(navLabel('/cloud-files'), '云端文件');
  assert.deepEqual(workspaceNavigationGroup('/cloud-files')?.items.slice(0, 2).map(item => item.path),
    ['/dashboard', '/cloud-files']);
});

test('directory browsing and reopened organizer jobs use the page’s own directory rail', () => {
  assert.equal(workspaceNavigationGroup('/dashboard'), undefined);
  assert.equal(workspaceNavigationGroup('/batch', '?operation=media-organize'), undefined);
  assert.equal(workspaceNavigationGroup('/batch', '?batch=123'), undefined);
});

test('tool details remain under their navigation group with their parent destination', () => {
  assert.equal(workspaceNavigationGroup('/scans/17/dedupe')?.label, '查找与核对');
  assert.equal(workspaceNavigationGroup('/workflows/8')?.label, '任务与设置');
  assert.equal(workspaceNavigationGroup('/batch')?.label, '整理与恢复');
});

test('scroll history distinguishes directory changes but not inspecting another item', () => {
  const folder = workspaceViewKey('/dashboard', '?directory=%2Fdata%2Fdemo');
  assert.equal(workspaceViewKey('/dashboard', '?directory=%2Fdata%2Fdemo&selected=example'), folder);
  assert.notEqual(workspaceViewKey('/dashboard', '?directory=%2Fdata'), folder);
  assert.notEqual(workspaceViewKey('/dashboard', '?view=overview'), folder);
  assert.equal(workspaceViewKey('/batch', '?preview=123'), workspaceViewKey('/batch', '?preview=456'));
});
