import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { ConsoleIcon } from './ConsoleIcon';

interface Toast {
  id: number;
  tone: 'success' | 'error' | 'info';
  text: string;
}

interface ToastActions {
  success: (text: string) => void;
  error: (text: string) => void;
  info: (text: string) => void;
  dismiss: () => void;
}

const ToastContext = createContext<ToastActions | null>(null);
let sequence = 0;

/** Keep errors readable and pause transient feedback while the user interacts with it. */
function ToastNotice({ toast, dismiss }: { toast: Toast; dismiss: (id: number) => void }) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (toast.tone === 'error' || hovered || focused) return;
    const timer = window.setTimeout(() => dismiss(toast.id), 6000);
    return () => window.clearTimeout(timer);
  }, [toast, hovered, focused, dismiss]);

  return <div className={'nfc-v2-toast nfc-v2-toast-' + toast.tone}
    onPointerEnter={() => setHovered(true)} onPointerLeave={() => setHovered(false)}
    onFocus={() => setFocused(true)} onBlur={event => {
      if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
    }}
    role={toast.tone === 'error' ? 'alert' : 'status'}
    aria-live={toast.tone === 'error' ? 'assertive' : 'polite'}>
    <ConsoleIcon name={toast.tone === 'error' ? 'x' : toast.tone === 'info' ? 'info' : 'check-circle'} size={19} />
    <span>{toast.text}</span>
    <button type="button" onClick={() => dismiss(toast.id)} aria-label="关闭通知"><ConsoleIcon name="x" size={17} /></button>
  </div>;
}

export const ConsoleToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toast, setToast] = useState<Toast | null>(null);
  const dismissNotice = useCallback((id: number) => {
    setToast(current => current?.id === id ? null : current);
  }, []);
  const show = useCallback((tone: Toast['tone'], text: string) => {
    setToast({ id: ++sequence, tone, text });
  }, []);
  const actions = useMemo<ToastActions>(() => ({
    success: text => show('success', text),
    error: text => show('error', text),
    info: text => show('info', text),
    dismiss: () => setToast(null),
  }), [show]);

  return (
    <ToastContext.Provider value={actions}>
      {children}
      {toast && <ToastNotice key={toast.id} toast={toast} dismiss={dismissNotice} />}
    </ToastContext.Provider>
  );
};

export function useConsoleToast(): ToastActions {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useConsoleToast requires ConsoleToastProvider');
  return context;
}
