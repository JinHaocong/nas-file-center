import { type CSSProperties, type ReactElement } from 'react';

interface Props {
  value: number;
  children: ReactElement;
}

/** Animate the paint layer while the native meter reports the real value immediately. */
export function ProgressMotionTrack({ value, children }: Props) {
  const fraction = Math.min(100, Math.max(0, Number.isFinite(value) ? value : 0)) / 100;
  return (
    <span className="nfc-progress-motion" style={{ '--nfc-progress-fraction': fraction } as CSSProperties}>
      {children}
      <span className="nfc-progress-motion-fill" aria-hidden="true" />
    </span>
  );
}
