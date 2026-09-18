import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.0 C6A settings login and directory picker contract', () => {
  test('Login uses the restrained product shell without legacy gradient card treatment', () => {
    const source = read('src/pages/Login/index.tsx');
    assert.match(source, /nfc-login-shell/);
    assert.match(source, /nfc-login-panel/);
    assert.match(source, /nfc-login-brand/);
    assert.match(source, /NAS File Center v0\.4\.0/);
    assert.doesNotMatch(source, /<Card\b/);
    assert.doesNotMatch(source, /linear-gradient/);
  });

  test('Settings uses shared v0.4.0 surfaces and responsive session view', () => {
    const source = read('src/pages/Settings/index.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar', 'ResponsiveDescriptions', 'ResponsiveDataView', 'CodePath']) {
      assert.match(source, new RegExp(symbol));
    }
    assert.match(source, /nfc-session-mobile-card/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Settings preserves all security, retention, resource and session gates', () => {
    const source = read('src/pages/Settings/index.tsx');
    for (const semantic of [
      'ALLOW_MUTATION',
      'ALLOW_DELETE',
      'isAdmin',
      'validateRetentionDaysInput',
      'getAuditRetentionApplyAvailability',
      'validateResourcePolicyUpdate',
      'revokeSession',
      'applyRetention',
      'updateRetentionPolicy',
    ]) {
      assert.match(source, new RegExp(semantic));
    }
  });

  test('DirectoryPicker uses product path surfaces instead of a legacy Card wrapper', () => {
    const source = read('src/components/DirectoryPicker/DirectoryPicker.tsx');
    assert.match(source, /CodePath/);
    assert.match(source, /nfc-directory-picker/);
    assert.match(source, /nfc-directory-picker-selection/);
    assert.match(source, /高级：手动多行输入路径/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('DirectoryPicker modal is responsive and keeps browse/favorites/recent behavior', () => {
    const source = read('src/components/DirectoryPicker/DirectoryPickerModal.tsx');
    assert.match(source, /useResponsive/);
    assert.match(source, /nfc-directory-picker-modal/);
    assert.match(source, /nfc-directory-browser-toolbar/);
    for (const semantic of ['listDirectory', 'listFavorites', 'listRecent', 'recordRecent', 'addFavorite', 'deleteFavorite']) {
      assert.match(source, new RegExp(semantic));
    }
  });

  test('C6A CSS defines login, settings and picker responsive surfaces', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-login-shell',
      '.nfc-login-panel',
      '.nfc-settings-grid',
      '.nfc-session-mobile-card',
      '.nfc-directory-picker',
      '.nfc-directory-picker-selection',
      '.nfc-directory-picker-modal',
      '.nfc-directory-browser-toolbar',
    ]) {
      assert.match(css, new RegExp(selector.replace('.', '\\.')));
    }
  });
});
