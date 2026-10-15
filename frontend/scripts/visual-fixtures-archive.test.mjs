/** Stage 5E-AI: shared Archive Recovery synthetic visual data contract. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  visualArchiveDirectoryFixture, visualAdminFixture, visualSafeSettingsFixture,
  visualThemes, visualViewports,
} from './visual-fixtures.mjs';

test('exact eight UI review widths and four effective theme variants', () => {
  assert.deepEqual([...visualViewports], [360, 390, 430, 768, 1024, 1280, 1440, 1920]);
  assert.equal(visualViewports.length * visualThemes.length, 32);
  assert.deepEqual(visualThemes.map(v => [v.mode, v.effective]),
    [['light', 'light'], ['dark', 'dark'],
      ['system', 'light'], ['system', 'dark']]);
  assert.ok(Object.isFrozen(visualViewports));
  assert.ok(Object.isFrozen(visualThemes));
});

test('reusable directory fixture is GET-only synthetic and deterministic', () => {
  const fixture = visualArchiveDirectoryFixture('/data');
  assert.deepEqual(fixture, {
    path: '/data', parent: null, allowed_roots: ['/data'],
    items: [{ name: 'fixture.zip', path: '/data/fixture.zip',
      type: 'file', is_dir: false, size: 123 }],
    total: 1, page: 1, page_size: 100, has_more: false,
  });
  assert.equal(visualArchiveDirectoryFixture('/data', 'demo.zip').items[0].path,
    '/data/demo.zip');
  assert.deepEqual(visualArchiveDirectoryFixture('/data/other').items, []);
  assert.equal(visualArchiveDirectoryFixture('/data/other').total, 0);
  const first = visualArchiveDirectoryFixture('/data');
  first.items.pop();
  first.allowed_roots.pop();
  assert.deepEqual(visualArchiveDirectoryFixture('/data').items, fixture.items);
  assert.deepEqual(visualArchiveDirectoryFixture('/data').allowed_roots, ['/data']);
});

test('fixture identity and safety flags never claim live NAS access', () => {
  assert.deepEqual(visualAdminFixture('nfc-readonly-synthetic'), {
    id: 1, username: 'nfc-readonly-synthetic', role: 'admin', is_admin: true,
  });
  assert.deepEqual(visualSafeSettingsFixture(), {
    allow_mutation: false, allow_delete: false, safe_mode: true,
  });
});
