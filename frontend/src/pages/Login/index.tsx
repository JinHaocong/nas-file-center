import React, { useState } from 'react';
import { Alert, Button, Dropdown, Form, Input } from 'antd';
import type { MenuProps } from 'antd';
import {
  DesktopOutlined,
  HddOutlined,
  LockOutlined,
  MoonOutlined,
  SunOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useTheme } from '../../contexts/ThemeContext';
import { useTitle } from '../../hooks/useTitle';

export const LoginPage: React.FC = () => {
  useTitle('用户登录');
  const { login, isAuthenticated } = useAuth();
  const { mode, setMode } = useTheme();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  const onFinish = async (values: any) => {
    try {
      setLoading(true);
      setErrorMessage(null);
      await login(values);
      navigate('/dashboard', { replace: true });
    } catch (err: any) {
      setErrorMessage(err.message || '登录失败，请检查用户名或密码');
    } finally {
      setLoading(false);
    }
  };

  const themeMenuItems: MenuProps['items'] = [
    { key: 'light', icon: <SunOutlined />, label: '浅色模式', onClick: () => setMode('light') },
    { key: 'dark', icon: <MoonOutlined />, label: '深色模式', onClick: () => setMode('dark') },
    { key: 'system', icon: <DesktopOutlined />, label: '跟随系统', onClick: () => setMode('system') },
  ];

  return (
    <main className="nfc-login-shell">
      <div className="nfc-login-theme">
        <Dropdown menu={{ items: themeMenuItems, selectedKeys: [mode] }} trigger={['click']}>
          <Button
            type="text"
            className="nfc-touch-button"
            aria-label="切换登录页主题"
            icon={mode === 'dark' ? <MoonOutlined /> : mode === 'light' ? <SunOutlined /> : <DesktopOutlined />}
          >
            <span className="nfc-login-theme-label">{mode}</span>
          </Button>
        </Dropdown>
      </div>

      <section className="nfc-login-panel" aria-labelledby="nfc-login-title">
        <div className="nfc-login-brand">
          <span className="nfc-login-brand-mark" aria-hidden="true">
            <HddOutlined />
          </span>
          <div>
            <div className="nfc-page-eyebrow">NAS OPERATIONS CONSOLE</div>
            <h1 id="nfc-login-title">NAS File Center</h1>
            <p>面向大容量 NAS 数据的扫描、计划、隔离与安全批处理中心。</p>
          </div>
        </div>

        <div className="nfc-login-divider" />

        {errorMessage && (
          <Alert
            message={errorMessage}
            type="error"
            showIcon
            closable
            onClose={() => setErrorMessage(null)}
            className="nfc-login-alert"
          />
        )}

        <Form layout="vertical" onFinish={onFinish} size="large" requiredMark={false}>
          <Form.Item
            name="username"
            label="管理员账号"
            rules={[{ required: true, message: '请输入管理员账号' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>

          <Form.Item
            name="password"
            label="管理密码"
            rules={[{ required: true, message: '请输入管理密码' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
          </Form.Item>

          <Button type="primary" htmlType="submit" loading={loading} block className="nfc-login-submit">
            安全登录
          </Button>
        </Form>

        <div className="nfc-login-security-note">
          登录后所有真实文件变更仍受 Safe Mode、Plan 生命周期和服务端安全策略约束。
        </div>
      </section>

      <footer className="nfc-login-footer">NAS File Center v0.4.4 · Docker / NAS</footer>
    </main>
  );
};
