import React, { useRef, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';

import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';

import { useAuth } from '../../contexts/AuthContext';
import { useTheme, type ThemeMode } from '../../contexts/ThemeContext';
import { useTitle } from '../../hooks/useTitle';

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

  /** Keep one login request in flight, including duplicate form submissions before React renders. */
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
      <header className="nfc-v2-login-toolbar">
        <div className="nfc-login-brand">
          <span className="nfc-login-brand-mark" aria-hidden="true">
            <ConsoleIcon name="hard-drive" size={21} />
          </span>
          <span>NAS File Center</span>
        </div>
        <div className="nfc-login-theme">
          <ConsoleIcon className="nfc-v2-login-theme-label"
            name={mode === 'dark' ? 'moon' : mode === 'light' ? 'sun' : 'settings'} size={16} />
          <select id="nfc-login-theme-select" value={mode}
            aria-label="切换登录页主题"
            onChange={event => setMode(event.target.value as ThemeMode)}>
            <option value="light">浅色模式</option>
            <option value="dark">深色模式</option>
            <option value="system">跟随系统</option>
          </select>
          <ConsoleIcon className="nfc-v2-login-theme-chevron" name="chevron-down" size={14} />
        </div>
      </header>

      <div className="nfc-v2-login-layout">
        <section className="nfc-login-panel" aria-labelledby="nfc-login-title">
          <h1 id="nfc-login-title" className="nfc-v2-login-heading">登录文件空间</h1>

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
                  value={username} disabled={loading} autoComplete="username" autoCapitalize="none"
                  spellCheck={false} onChange={event => setUsername(event.target.value)} />
              </div>
            </div>

            <div className="nfc-v2-login-field">
              <label htmlFor="nfc-login-password">管理密码</label>
              <div className="nfc-v2-login-input-wrap">
                <ConsoleIcon name="lock" size={18} />
                <input id="nfc-login-password" type="password" name="password" required
                  value={password} disabled={loading} autoComplete="current-password"
                  onChange={event => setPassword(event.target.value)} />
              </div>
            </div>

            <ConsoleButton type="submit" variant="primary" loading={loading}
              disabled={loading || !username.trim() || !password}
              className="nfc-login-submit">
              {loading ? '登录中…' : '登录'}
            </ConsoleButton>
          </form>
        </section>
      </div>

      <footer className="nfc-login-footer">NAS File Center v1.8.1</footer>
    </main>
  );
};
