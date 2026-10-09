import React, { useEffect, useId, useRef, useState } from 'react';
import { authApi } from '../api/auth';
import { ConsoleButton } from './ui/ConsoleButton';
import { ConsoleIcon } from './ui/ConsoleIcon';
import { useConsoleToast } from './ui/ConsoleToast';
import { validatePasswordChange } from './ui/passwordValidation';

interface Props {
  open: boolean;
  onClose: () => void;
}

export const ChangePasswordModal: React.FC<Props> = ({ open, onClose }) => {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const firstInputRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const descriptionId = useId();
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

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      firstInputRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

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
      await authApi.changePassword({ old_password: oldPassword, new_password: newPassword });
      reset();
      onClose();
      toast.success('密码修改成功，其他设备会话已安全注销');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '修改管理员密码失败';
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <dialog className="nfc-v2-dialog nfc-change-password-modal nfc-overlay-modal"
      ref={dialogRef} aria-labelledby={titleId} aria-describedby={descriptionId}
      onCancel={event => {
        event.preventDefault();
        close();
      }}>
      <div className="nfc-v2-dialog-heading">
        <span className="nfc-v2-dialog-icon"><ConsoleIcon name="lock" size={20} /></span>
        <div>
          <h2 id={titleId}>修改管理员密码</h2>
          <p id={descriptionId}>请先验证旧密码。更新成功后其他设备会话将安全注销。</p>
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
    </dialog>
  );
};
