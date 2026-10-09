import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { validatePasswordChange } from '../src/components/ui/passwordValidation';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 native administrator security dialog', () => {
  test('password validation rejects missing, short and mismatched credentials', () => {
    assert.equal(validatePasswordChange({
      oldPassword: '', newPassword: 'abcdef', confirmPassword: 'abcdef',
    }), '请输入当前旧密码');
    assert.equal(validatePasswordChange({
      oldPassword: 'old', newPassword: '', confirmPassword: '',
    }), '请输入新密码');
    assert.equal(validatePasswordChange({
      oldPassword: 'old', newPassword: 'abcde', confirmPassword: 'abcde',
    }), '新密码长度不能少于6位');
    assert.equal(validatePasswordChange({
      oldPassword: 'old', newPassword: 'abcdef', confirmPassword: 'fedcba',
    }), '两次输入的新密码不一致');
    assert.equal(validatePasswordChange({
      oldPassword: 'old', newPassword: 'abcdef', confirmPassword: 'abcdef',
    }), null);
  });

  test('native modal preserves old-password verification and server API', () => {
    const source = read('src/components/ChangePasswordModal.tsx');
    assert.match(source, /<dialog/);
    assert.match(source, /showModal\(\)/);
    assert.match(source, /onCancel=/);
    assert.match(source, /authApi\.changePassword/);
    assert.match(source, /old_password: oldPassword/);
    assert.match(source, /new_password: newPassword/);
    assert.match(source, /autoComplete="current-password"/);
    assert.match(source, /autoComplete="new-password"/);
    assert.match(source, /validatePasswordChange/);
    assert.match(source, /disabled=\{submitting\}/);
    assert.doesNotMatch(source, /from ['"](?:antd|@ant-design\/icons)['"]/);
  });

  test('toast provider is shared and announces failures', () => {
    const source = read('src/components/ui/ConsoleToast.tsx');
    const app = read('src/App.tsx');
    assert.match(app, /<ConsoleToastProvider>/);
    assert.match(source, /role=\{toast\.tone === 'error' \? 'alert' : 'status'\}/);
    assert.match(source, /aria-live=/);
    assert.match(source, /window\.clearTimeout/);
    assert.doesNotMatch(source, /from ['"](?:antd|@ant-design\/icons)['"]/);
  });

  test('native security modal and toast have light-dark responsive CSS', () => {
    const css = read('src/styles/console-v2.css');
    assert.match(css, /\.nfc-v2-dialog::backdrop/);
    assert.match(css, /\.nfc-v2-dialog-form input/);
    assert.match(css, /\.nfc-v2-toast-error/);
    assert.match(css, /\[data-theme='dark'\] \.nfc-v2-toast/);
    assert.match(css, /@media \(max-width: 767px\)/);
  });
});
