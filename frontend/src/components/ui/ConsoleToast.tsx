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
}

const ToastContext = createContext<ToastActions | null>(null);
let sequence = 0;

export const ConsoleToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toast, setToast] = useState<Toast | null>(null);
  const show = useCallback((tone: Toast['tone'], text: string) => {
    setToast({ id: ++sequence, tone, text });
  }, []);
  const actions = useMemo<ToastActions>(() => ({
    success: text => show('success', text),
    error: text => show('error', text),
    info: text => show('info', text),
  }), [show]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(current => current?.id === toast.id ? null : current), 6000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  return (
    <ToastContext.Provider value={actions}>
      {children}
      {toast && (
        <div className={'nfc-v2-toast nfc-v2-toast-' + toast.tone}
          role={toast.tone === 'error' ? 'alert' : 'status'}
          aria-live={toast.tone === 'error' ? 'assertive' : 'polite'}>
          <ConsoleIcon name={toast.tone === 'error' ? 'x' : 'check-circle'} size={19} />
          <span>{toast.text}</span>
          <button type="button" onClick={() => setToast(null)}
            aria-label="关闭通知"><ConsoleIcon name="x" size={17} /></button>
        </div>
      )}
    </ToastContext.Provider>
  );
};

export function useConsoleToast(): ToastActions {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useConsoleToast requires ConsoleToastProvider');
  return context;
}
