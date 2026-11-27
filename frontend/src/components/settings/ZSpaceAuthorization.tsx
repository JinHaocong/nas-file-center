import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { ConsoleSheet } from '../ui/ConsoleSheet';
import { getStructuredApiError } from '../../api/errors';
import { zspaceAuthorizationApi, type ZSpaceAuthorizationAttempt } from '../../api/zspaceAuthorization';

const queryKey = ['settings', 'zspace-authorization'] as const;
const statusLabels = {
  authorized: '已授权',
  needs_login: '待授权',
  unconfigured: '待配置',
  unavailable: '连接不可用',
};

interface PendingAuthorization extends ZSpaceAuthorizationAttempt {
  deadline: number;
}

/** Open only the HTTPS authorization page of the official ZSpace service. */
function isAuthorizationUrl(value: string) {
  try {
    const url = new URL(value);
    return url.origin === 'https://oauth.zconnect.cn' && url.pathname === '/wbui/authorize' &&
      !url.username && !url.password && !url.hash && url.searchParams.has('state');
  } catch {
    return false;
  }
}

/** Keep one browser authorization request active and discard its code after submission. */
export function ZSpaceAuthorization() {
  const client = useQueryClient();
  const statusQuery = useQuery({ queryKey, queryFn: zspaceAuthorizationApi.status, retry: false });
  const [attempt, setAttempt] = useState<PendingAuthorization | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [busy, setBusy] = useState<'start' | 'complete' | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const current = useRef<PendingAuthorization | null>(null);
  const mounted = useRef(false);
  const action = useRef(false);
  const codeField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (current.current) void zspaceAuthorizationApi.cancel(current.current.id).catch(() => {});
    };
  }, []);

  useEffect(() => {
    if (!attempt) return;
    const deadline = attempt.deadline;
    /** Recalculate from the deadline so switching browser tabs cannot extend the window. */
    function updateRemaining() {
      setSeconds(Math.max(0, Math.ceil((deadline - Date.now()) / 1000)));
    }
    updateRemaining();
    const timer = setInterval(updateRemaining, 1000);
    return () => clearInterval(timer);
  }, [attempt]);

  /** Clear the local challenge and ask the backend to stop its pending CLI process. */
  function clearAttempt() {
    const id = current.current?.id;
    current.current = null;
    setAttempt(null);
    setError('');
    return id ? zspaceAuthorizationApi.cancel(id).catch(() => {}) : Promise.resolve();
  }

  /** Request a new link only after releasing any locally held attempt. */
  async function start() {
    if (action.current) return;
    action.current = true;
    setBusy('start');
    setNotice('');
    await clearAttempt();
    try {
      const result = await zspaceAuthorizationApi.start();
      if (!mounted.current || !isAuthorizationUrl(result.url) ||
          !Number.isInteger(result.expires_in) || result.expires_in <= 0 || result.expires_in > 180) {
        void zspaceAuthorizationApi.cancel(result.id).catch(() => {});
        if (mounted.current) setError('未能取得有效的极空间授权链接，请重试。');
        return;
      }
      const pending = { ...result, deadline: Date.now() + result.expires_in * 1000 };
      current.current = pending;
      setSeconds(result.expires_in);
      setAttempt(pending);
    } catch (failure) {
      if (mounted.current) setError(getStructuredApiError(failure).message || '无法发起极空间授权。');
    } finally {
      action.current = false;
      if (mounted.current) setBusy(null);
    }
  }

  /** Read the one-time code from the form only when submitting it. */
  async function complete(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const pending = current.current;
    const field = codeField.current;
    if (action.current || !pending || !field || Date.now() >= pending.deadline) return;
    const code = field.value.trim();
    if (!code) {
      field.focus();
      return;
    }
    field.value = '';
    action.current = true;
    setBusy('complete');
    setError('');
    try {
      const result = await zspaceAuthorizationApi.complete(pending.id, code);
      if (!mounted.current) return;
      current.current = null;
      setAttempt(null);
      client.setQueryData(queryKey, { status: result.status });
      setNotice('极空间授权完成。');
    } catch (failure) {
      if (mounted.current) setError(getStructuredApiError(failure).message || '授权未完成，请重新获取链接。');
    } finally {
      action.current = false;
      if (mounted.current) setBusy(null);
    }
  }

  const status = statusQuery.data?.status;
  const available = status === 'authorized' || status === 'needs_login';
  return (
    <section className="nfc-settings-subpanel" aria-labelledby="nfc-zspace-authorization">
      <div className="nfc-settings-subpanel-header">
        <div>
          <strong id="nfc-zspace-authorization">极空间授权</strong>
          <span>供 Worker 把整理时确认的附带文件送入极空间系统回收站。</span>
        </div>
        <span className="nfc-kind-badge" role="status">
          {statusQuery.isPending ? '正在读取' : status ? statusLabels[status] : '状态读取失败'}
        </span>
      </div>
      <div className="nfc-action-bar">
        {available && <ConsoleButton variant="primary" size="sm" loading={busy === 'start'}
          disabled={busy === 'complete'} onClick={() => { void start(); }}>
          {status === 'authorized' ? '重新授权' : '连接极空间'}
        </ConsoleButton>}
        <ConsoleButton size="sm" loading={statusQuery.isFetching} disabled={busy !== null}
          onClick={() => { void statusQuery.refetch(); }}>刷新授权状态</ConsoleButton>
      </div>
      {status === 'unconfigured' && <p className="nfc-settings-help">请在部署配置中为 API 和 Worker 配置极空间 CLI、共用授权卷和目录映射。</p>}
      {notice && <p className="nfc-settings-help" role="status">{notice}</p>}
      {!attempt && error && <p className="nfc-v2-settings-error" role="alert">{error}</p>}
      {attempt && <ConsoleSheet open title="极空间账号授权"
        description="在极空间网页选中设备并确认授权，再把网页显示的一次性授权码填到这里。"
        dismissDisabled={busy === 'complete'} onClose={() => { void clearAttempt(); }}>
        <form className="nfc-zspace-authorization-form" onSubmit={event => { void complete(event); }}>
          {seconds > 0 ? <>
            <a href={attempt.url} target="_blank" rel="noopener noreferrer"
              className="nfc-console-button nfc-console-button-secondary nfc-console-button-md">
              <ConsoleIcon name="arrow-right" size={16} />
              <span className="nfc-console-button-label">打开极空间授权页</span>
            </a>
            <label>
              <span>一次性授权码</span>
              <input ref={codeField} type="password" autoComplete="off" spellCheck={false}
                maxLength={64} required disabled={busy !== null} />
            </label>
            <p className="nfc-settings-help">链接剩余 {Math.floor(seconds / 60)} 分 {seconds % 60} 秒</p>
          </> : <p role="status">授权链接已过期，请重新获取。</p>}
          {error && <p className="nfc-v2-settings-error" role="alert">{error}</p>}
          <div className="nfc-action-bar">
            {seconds > 0 && <ConsoleButton type="submit" variant="primary" loading={busy === 'complete'}>
              完成授权
            </ConsoleButton>}
            <ConsoleButton variant="secondary" disabled={busy !== null} onClick={() => { void start(); }}>
              重新获取授权链接
            </ConsoleButton>
          </div>
        </form>
      </ConsoleSheet>}
    </section>
  );
}
