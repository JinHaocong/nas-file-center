import React, { useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { authApi } from '../api/auth';
import { ConsoleButton } from './ui/ConsoleButton';
import { ConsoleIcon } from './ui/ConsoleIcon';
import { useConsoleToast } from './ui/ConsoleToast';
import { validatePasswordChange } from './ui/passwordValidation';

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * Accessible Radix dialog. Escape/overlay dismissal is blocked while the
 * authenticated request is in flight; mutation still happens only at submit.
 */
export const ChangePasswordModal: React.FC<Props> = ({ open, onClose }) => {
  const firstInputRef = useRef<HTMLInputElement>(null);
  const toast = useConsoleToast();
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setOldPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setError(null);
  };

  const close = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    const validationError = validatePasswordChange({ oldPassword, newPassword, confirmPassword });
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await authApi.changePassword({
        old_password: oldPassword,
        new_password: newPassword,
      });
      reset();
      onClose();
      toast.success('密码修改成功，其他设备会话已安全注销');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '修改管理员密码失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={next => {
      if (!next && !submitting) close();
    }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay" />
        <Dialog.Content
          className="nfc-v2-dialog nfc-change-password-modal nfc-overlay-modal"
          onEscapeKeyDown={event => { if (submitting) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}
          onOpenAutoFocus={event => {
            event.preventDefault();
            firstInputRef.current?.focus();
          }}
        >
          <div className="nfc-v2-dialog-heading">
            <span className="nfc-v2-dialog-icon">
              <ConsoleIcon name="lock" size={20} />
            </span>
            <div>
              <Dialog.Title>修改管理员密码</Dialog.Title>
              <Dialog.Description>
                请先验证旧密码。更新成功后其他设备会话将安全注销。
              </Dialog.Description>
            </div>
            <button className="nfc-v2-dialog-close" type="button"
              aria-label="关闭密码修改窗口" disabled={submitting} onClick={close}>
              <ConsoleIcon name="x" size={18} />
            </button>
          </div>
          <form className="nfc-v2-dialog-form nfc-security-form" onSubmit={handleSubmit}>
            <label htmlFor="nfc-old-password">当前旧密码</label>
            <input ref={firstInputRef} id="nfc-old-password" type="password" required
              autoComplete="current-password" placeholder="请输入当前密码"
              disabled={submitting} value={oldPassword}
              onChange={event => setOldPassword(event.target.value)} />
            <label htmlFor="nfc-new-password">新密码</label>
            <input id="nfc-new-password" type="password" required minLength={6}
              autoComplete="new-password" placeholder="请输入新密码（至少6位）"
              disabled={submitting} value={newPassword}
              onChange={event => setNewPassword(event.target.value)} />
            <label htmlFor="nfc-confirm-password">确认新密码</label>
            <input id="nfc-confirm-password" type="password" required minLength={6}
              autoComplete="new-password" placeholder="请再次输入新密码"
              disabled={submitting} value={confirmPassword}
              onChange={event => setConfirmPassword(event.target.value)} />
            {error && <div className="nfc-v2-dialog-error" role="alert">{error}</div>}
            <div className="nfc-v2-dialog-footer">
              <ConsoleButton onClick={close} disabled={submitting}>取消</ConsoleButton>
              <ConsoleButton variant="primary" type="submit" loading={submitting}
                leadingIcon={<ConsoleIcon name="lock" size={16} />}>确认修改</ConsoleButton>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
