import React, { useRef, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useTheme, type ThemeMode } from '../../contexts/ThemeContext';
import { useTitle } from '../../hooks/useTitle';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleButton } from '../../components/ui/ConsoleButton';

export const LoginPage: React.FC = () => {
  useTitle('用户登录');
  const { login, isAuthenticated } = useAuth();
  const { mode, setMode } = useTheme();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const submissionInFlight = useRef(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submissionInFlight.current || isAuthenticated || !username.trim() || !password) return;
    submissionInFlight.current = true;
    setLoading(true);
    setErrorMessage(null);
    try {
      await login({ username, password });
      navigate('/dashboard', { replace: true });
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error && err.message ? err.message :
        '登录失败，请检查用户名或密码');
    } finally {
      submissionInFlight.current = false;
      setLoading(false);
    }
  };

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <main className="nfc-login-shell nfc-v2-login-shell">
      <div className="nfc-login-theme">
        <label htmlFor="nfc-login-theme-select" className="nfc-v2-login-theme-label">
          <ConsoleIcon name={mode === 'dark' ? 'moon' : mode === 'light' ? 'sun' : 'settings'} size={17} />
          <span>切换登录页主题</span>
        </label>
        <select id="nfc-login-theme-select" value={mode}
          aria-label="切换登录页主题"
          onChange={event => setMode(event.target.value as ThemeMode)}>
          <option value="light">浅色模式</option>
          <option value="dark">深色模式</option>
          <option value="system">跟随系统</option>
        </select>
      </div>

      <section className="nfc-login-panel" aria-labelledby="nfc-login-title">
        <div className="nfc-login-brand">
          <span className="nfc-login-brand-mark" aria-hidden="true">
            <ConsoleIcon name="hard-drive" size={21} />
          </span>
          <div>
            <div className="nfc-page-eyebrow">NAS OPERATIONS CONSOLE</div>
            <h1 id="nfc-login-title">NAS File Center</h1>
            <p>面向大容量 NAS 数据的扫描、计划、隔离与安全批处理中心。</p>
          </div>
        </div>

        <div className="nfc-login-divider" />

        {errorMessage && (
          <div className="nfc-login-alert nfc-v2-login-alert" role="alert">
            <ConsoleIcon name="info" size={17} />
            <span>{errorMessage}</span>
            <button type="button" aria-label="关闭登录错误提示"
              onClick={() => setErrorMessage(null)}>
              <ConsoleIcon name="x" size={17} />
            </button>
          </div>
        )}

        <form className="nfc-v2-login-form" onSubmit={event => { void onSubmit(event); }}
          aria-busy={loading}>
          <div className="nfc-v2-login-field">
            <label htmlFor="nfc-login-username">管理员账号</label>
            <div className="nfc-v2-login-input-wrap">
              <ConsoleIcon name="user" size={18} />
              <input id="nfc-login-username" type="text" name="username" required
                value={username} disabled={loading} autoComplete="username"
                placeholder="用户名" onChange={event => setUsername(event.target.value)} />
            </div>
          </div>

          <div className="nfc-v2-login-field">
            <label htmlFor="nfc-login-password">管理密码</label>
            <div className="nfc-v2-login-input-wrap">
              <ConsoleIcon name="lock" size={18} />
              <input id="nfc-login-password" type="password" name="password" required
                value={password} disabled={loading} autoComplete="current-password"
                placeholder="密码" onChange={event => setPassword(event.target.value)} />
            </div>
          </div>

          <ConsoleButton type="submit" variant="primary" loading={loading}
            disabled={loading || !username.trim() || !password}
            className="nfc-login-submit">
            安全登录
          </ConsoleButton>
        </form>

        <div className="nfc-login-security-note">
          登录后所有真实文件变更仍受 Safe Mode、Plan 生命周期和服务端安全策略约束。
        </div>
      </section>

      <footer className="nfc-login-footer">NAS File Center v0.4.7 · Docker / NAS</footer>
    </main>
  );
};
