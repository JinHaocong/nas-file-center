import assert from 'node:assert/strict';
import test from 'node:test';

import { consoleNavGroups, consoleNavigation, currentDestination, navLabel, workspaceViewKey } from '../src/components/layout/navItems';

test('cloud files has its own destination beside local files', () => {
  assert.equal(navLabel('/cloud-files'), '云端文件');
  assert.deepEqual(consoleNavGroups[0].items.slice(0, 2).map(item => item.path),
    ['/dashboard', '/cloud-files']);
});

test('the desktop navigation inventory gives each destination a single entry', () => {
  assert.equal(new Set(consoleNavigation.map(item => item.path)).size, consoleNavigation.length);
  assert.equal(currentDestination('/dashboard', '?directory=/data'), '/dashboard');
  assert.equal(currentDestination('/batch', '?operation=media-organize'), '/batch?operation=media-organize');
  assert.equal(currentDestination('/batch', '?batch=123'), '/batch?operation=media-organize');
});

test('tool details select their parent destination in the navigation rail', () => {
  assert.equal(currentDestination('/scans/17/dedupe', ''), '/scans');
  assert.equal(currentDestination('/workflows/8', ''), '/workflows');
  assert.equal(currentDestination('/batch', ''), '/batch');
});

test('scroll history distinguishes directory changes but not inspecting another item', () => {
  const folder = workspaceViewKey('/dashboard', '?directory=%2Fdata%2Fdemo');
  assert.equal(workspaceViewKey('/dashboard', '?directory=%2Fdata%2Fdemo&selected=example'), folder);
  assert.notEqual(workspaceViewKey('/dashboard', '?directory=%2Fdata'), folder);
  assert.notEqual(workspaceViewKey('/dashboard', '?view=overview'), folder);
  assert.equal(workspaceViewKey('/batch', '?preview=123'), workspaceViewKey('/batch', '?preview=456'));
});
