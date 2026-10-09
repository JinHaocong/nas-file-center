export interface PasswordChangeValues {
  oldPassword: string;
  newPassword: string;
  confirmPassword: string;
}

export function validatePasswordChange(values: PasswordChangeValues): string | null {
  if (!values.oldPassword) return '请输入当前旧密码';
  if (!values.newPassword) return '请输入新密码';
  if (values.newPassword.length < 6) return '新密码长度不能少于6位';
  if (values.newPassword !== values.confirmPassword) return '两次输入的新密码不一致';
  return null;
}
