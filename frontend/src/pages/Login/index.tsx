import React, { useState } from 'react';
import { Card, Form, Input, Button, Typography, Alert, Dropdown, MenuProps } from 'antd';
import {
  UserOutlined,
  LockOutlined,
  HddOutlined,
  SunOutlined,
  MoonOutlined,
  DesktopOutlined,
} from '@ant-design/icons';
import { useNavigate, Navigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useTheme } from '../../contexts/ThemeContext';
import { useTitle } from '../../hooks/useTitle';

const { Title, Text } = Typography;

export const LoginPage: React.FC = () => {
  useTitle('用户登录');
  const { login, isAuthenticated } = useAuth();
  const { mode, setMode, isDark } = useTheme();
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
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        background: isDark
          ? 'linear-gradient(135deg, #0d1117 0%, #161b22 100%)'
          : 'linear-gradient(135deg, #f0f5ff 0%, #e6f4ff 100%)',
        position: 'relative',
        padding: 24,
      }}
    >
      <div style={{ position: 'absolute', top: 24, right: 24 }}>
        <Dropdown menu={{ items: themeMenuItems, selectedKeys: [mode] }} trigger={['click']}>
          <Button
            type="text"
            icon={mode === 'dark' ? <MoonOutlined /> : mode === 'light' ? <SunOutlined /> : <DesktopOutlined />}
          >
            <span style={{ marginLeft: 4, textTransform: 'capitalize' }}>{mode}</span>
          </Button>
        </Dropdown>
      </div>

      <Card
        style={{
          width: '100%',
          maxWidth: 420,
          borderRadius: 16,
          boxShadow: isDark
            ? '0 8px 24px rgba(0, 0, 0, 0.5)'
            : '0 8px 24px rgba(22, 119, 255, 0.08)',
        }}
        bodyStyle={{ padding: '36px 32px' }}
      >
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div
            style={{
              width: 52,
              height: 52,
              borderRadius: 14,
              background: 'linear-gradient(135deg, #1677ff 0%, #0958d9 100%)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontSize: 26,
              marginBottom: 12,
              boxShadow: '0 4px 12px rgba(22, 119, 255, 0.3)',
            }}
          >
            <HddOutlined />
          </div>
          <Title level={3} style={{ margin: 0 }}>
            NAS File Center
          </Title>
          <Text type="secondary" style={{ fontSize: 13, marginTop: 4, display: 'block' }}>
            面向几十 TB NAS 数据的去重与批处理中心
          </Text>
        </div>

        {errorMessage && (
          <Alert
            message={errorMessage}
            type="error"
            showIcon
            closable
            onClose={() => setErrorMessage(null)}
            style={{ marginBottom: 20 }}
          />
        )}

        <Form layout="vertical" onFinish={onFinish} size="large" requiredMark={false}>
          <Form.Item
            name="username"
            label="管理员账号"
            rules={[{ required: true, message: '请输入管理员账号' }]}
          >
            <Input prefix={<UserOutlined style={{ color: '#8c8c8c' }} />} placeholder="用户名" />
          </Form.Item>

          <Form.Item
            name="password"
            label="管理密码"
            rules={[{ required: true, message: '请输入管理密码' }]}
          >
            <Input.Password prefix={<LockOutlined style={{ color: '#8c8c8c' }} />} placeholder="密码" />
          </Form.Item>

          <Form.Item style={{ marginTop: 24, marginBottom: 8 }}>
            <Button type="primary" htmlType="submit" loading={loading} block style={{ height: 44 }}>
              安全登录
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <div style={{ marginTop: 24, textAlign: 'center' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          NAS File Center v0.3.1 • 极空间 / Zoraxy / Docker
        </Text>
      </div>
    </div>
  );
};
