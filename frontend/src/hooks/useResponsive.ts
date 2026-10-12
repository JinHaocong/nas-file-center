import { useSyncExternalStore } from 'react';

/** Match AntD Grid md (768px) and xl (1200px) boundaries without its runtime. */
export interface ResponsiveState {
  isMobile: boolean;
  isTablet: boolean;
  isDesktop: boolean;
}

const readWidth = (): number => (typeof window !== 'undefined' ? window.innerWidth : 0);
const subscribe = (onChange: () => void) => {
  if (typeof window === 'undefined') return () => {};
  window.addEventListener('resize', onChange, { passive: true });
  return () => window.removeEventListener('resize', onChange);
};

/** Deliberately preserve the initial SSR/mobile fallback of useBreakpoint. */
export const useResponsive = (): ResponsiveState => {
  const width = useSyncExternalStore(subscribe, readWidth, () => 0);
  const isMobile = width < 768;
  const isDesktop = width >= 1200;
  const isTablet = !isMobile && !isDesktop;
  return { isMobile, isTablet, isDesktop };
};
